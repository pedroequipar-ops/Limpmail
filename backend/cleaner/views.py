from django.db.models import Q
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Account, EmailRecord, Instruction, Job
from .serializers import AccountSerializer, EmailRecordSerializer, InstructionSerializer, JobSerializer
from .services import imap_pool, job_runner
from .services.imap_pool import ImapConnectionError

VALID_CATEGORIES = ('IMPORTANTE', 'SPAM', 'LIXEIRA')


@api_view(['POST'])
def test_connection(request):
    data = request.data
    host = data.get('host')
    port = data.get('port', 993)
    email = data.get('email')
    password = data.get('password')

    if not all([host, port, email, password]):
        return Response({'ok': False, 'error': 'host, port, email e password são obrigatórios'}, status=400)

    try:
        conn = imap_pool.connect(host, port, email, password)
    except ImapConnectionError as exc:
        return Response({'ok': False, 'error': str(exc)}, status=200)

    try:
        discovery = imap_pool.discover_special_folders(conn)
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return Response({'ok': True, **discovery})


@api_view(['GET', 'POST'])
def account_view(request):
    account = Account.objects.first()

    if request.method == 'GET':
        if not account:
            return Response(None)
        return Response(AccountSerializer(account).data)

    data = request.data
    required = ['host', 'port', 'email', 'password']
    if not account and not all(data.get(f) for f in required):
        return Response({'error': 'host, port, email e password são obrigatórios'}, status=400)

    if not account:
        account = Account()

    for field in ['provider', 'host', 'port', 'email', 'password', 'spam_folder', 'trash_folder']:
        if field in data and data[field] not in (None, ''):
            setattr(account, field, data[field])
    account.save()
    return Response(AccountSerializer(account).data, status=201)


@api_view(['GET', 'PUT'])
def instruction_view(request):
    instruction, _ = Instruction.objects.get_or_create(id=1)

    if request.method == 'GET':
        return Response(InstructionSerializer(instruction).data)

    text = request.data.get('text', '')
    instruction.text = text
    instruction.save()
    return Response(InstructionSerializer(instruction).data)


@api_view(['POST'])
def start_job(request):
    account = Account.objects.first()
    if not account:
        return Response({'error': 'nenhuma conta configurada'}, status=400)

    job = Job.objects.filter(account=account).exclude(status='completed').order_by('-created_at').first()
    if not job:
        job = Job.objects.create(account=account, status='fetching')

    started = job_runner.start_or_resume_job(job)
    return Response({'job': JobSerializer(job).data, 'started': started})


@api_view(['GET'])
def current_job(request):
    account = Account.objects.first()
    if not account:
        return Response(None)

    job = Job.objects.filter(account=account).order_by('-created_at').first()
    if not job:
        return Response(None)

    return Response(_job_status_payload(job))


@api_view(['POST'])
def resume_job(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    started = job_runner.start_or_resume_job(job)
    return Response({'job': JobSerializer(job).data, 'started': started})


@api_view(['GET'])
def job_status(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    return Response(_job_status_payload(job))


def _job_status_payload(job):
    with_final = EmailRecord.objects.filter(job=job).annotate(final_cat=Coalesce('user_override', 'ai_category'))
    counts = {category: with_final.filter(final_cat=category).count() for category in VALID_CATEGORIES}
    classify_pending = EmailRecord.objects.filter(job=job, classify_status='pending').count()
    classify_failed = EmailRecord.objects.filter(job=job, classify_status='failed').count()
    classify_done = EmailRecord.objects.filter(job=job, classify_status='done').count()
    fetched = EmailRecord.objects.filter(job=job).count()

    return {
        'job': JobSerializer(job).data,
        'running': job_runner.is_running(job.id),
        'fetched': fetched,
        'classify_pending': classify_pending,
        'classify_failed': classify_failed,
        'classify_done': classify_done,
        'counts': counts,
    }


@api_view(['GET'])
def job_emails(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    category = request.query_params.get('category')
    page = max(int(request.query_params.get('page', 1)), 1)
    page_size = min(max(int(request.query_params.get('page_size', 100)), 1), 500)

    qs = EmailRecord.objects.filter(job=job).order_by('id')
    if category in VALID_CATEGORIES:
        qs = qs.filter(Q(user_override=category) | Q(user_override__isnull=True, ai_category=category))

    total = qs.count()
    start = (page - 1) * page_size
    items = qs[start:start + page_size]

    return Response({
        'total': total,
        'page': page,
        'page_size': page_size,
        'results': EmailRecordSerializer(items, many=True).data,
    })


@api_view(['PATCH'])
def update_email(request, email_id):
    record = get_object_or_404(EmailRecord, id=email_id)
    category = request.data.get('user_override', None)

    if category is not None and category not in VALID_CATEGORIES:
        return Response({'error': f'categoria inválida: {category}'}, status=400)

    record.user_override = category or None

    if record.apply_status in ('not_applicable', 'pending', 'failed'):
        final = record.final_category
        record.apply_status = 'not_applicable' if final == 'IMPORTANTE' else 'pending'

    record.save(update_fields=['user_override', 'apply_status', 'updated_at'])
    return Response(EmailRecordSerializer(record).data)


@api_view(['POST'])
def apply_job(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    if job_runner.is_apply_running(job.id):
        return Response({'started': False, 'message': 'aplicação já em andamento'})

    started = job_runner.start_apply(job)
    return Response({'started': started})


@api_view(['GET'])
def apply_status(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    qs = EmailRecord.objects.filter(job=job).exclude(apply_status='not_applicable')
    counts = {
        'pending': qs.filter(apply_status='pending').count(),
        'applied': qs.filter(apply_status='applied').count(),
        'failed': qs.filter(apply_status='failed').count(),
    }
    return Response({
        'job': JobSerializer(job).data,
        'running': job_runner.is_apply_running(job.id),
        'counts': counts,
    })
