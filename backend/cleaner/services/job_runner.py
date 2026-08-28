import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from ..models import EmailRecord, Instruction, Job
from . import classify, fetch, imap_pool

DB_WRITE_LOCK = threading.Lock()

_running_jobs = set()
_running_lock = threading.Lock()

_cancel_requested = set()
_cancel_lock = threading.Lock()


class JobCancelled(Exception):
    pass


def is_running(job_id):
    with _running_lock:
        return job_id in _running_jobs


def request_cancel(job_id):
    with _cancel_lock:
        _cancel_requested.add(job_id)


def is_cancelled(job_id):
    with _cancel_lock:
        return job_id in _cancel_requested


def _clear_cancel(job_id):
    with _cancel_lock:
        _cancel_requested.discard(job_id)


def _mark_running(job_id):
    with _running_lock:
        if job_id in _running_jobs:
            return False
        _running_jobs.add(job_id)
        return True


def _unmark_running(job_id):
    with _running_lock:
        _running_jobs.discard(job_id)


def start_or_resume_job(job):
    """Inicia (ou retoma) o pipeline de fetch+classify em background thread. No-op se já rodando."""
    if not _mark_running(job.id):
        return False
    thread = threading.Thread(target=_run_job, args=(job.id,), daemon=True)
    thread.start()
    return True


def start_apply(job):
    """Inicia a fase de aplicação (mover de fato) em background thread. No-op se já rodando."""
    apply_key = f'apply-{job.id}'
    if not _mark_running(apply_key):
        return False
    thread = threading.Thread(target=_run_apply, args=(job.id,), daemon=True)
    thread.start()
    return True


def is_apply_running(job_id):
    return is_running(f'apply-{job_id}')


def _run_job(job_id):
    job = Job.objects.get(id=job_id)
    try:
        account = job.account
        conn = imap_pool.connect(account.host, account.port, account.email, account.password)
        try:
            imap_pool.select_inbox(conn, readonly=True)
            _fetch_phase(job, conn)
            _classify_phase(job)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

        with DB_WRITE_LOCK:
            job.status = 'reviewing'
            job.error_message = ''
            job.save(update_fields=['status', 'error_message', 'updated_at'])
    except JobCancelled:
        with DB_WRITE_LOCK:
            job.delete()
    except Exception as exc:
        with DB_WRITE_LOCK:
            job.error_message = str(exc)
            job.save(update_fields=['error_message', 'updated_at'])
    finally:
        _unmark_running(job_id)
        _clear_cancel(job_id)


def _fetch_phase(job, conn):
    with DB_WRITE_LOCK:
        job.status = 'fetching'
        job.save(update_fields=['status', 'updated_at'])

    all_uids = fetch.search_all_uids(conn)
    with DB_WRITE_LOCK:
        job.total_uids = len(all_uids)
        job.save(update_fields=['total_uids', 'updated_at'])

    existing_uids = set(EmailRecord.objects.filter(job=job).values_list('uid', flat=True))
    remaining = [u for u in all_uids if u not in existing_uids]

    for batch in fetch.chunked(remaining, settings.FETCH_BATCH_SIZE):
        if is_cancelled(job.id):
            raise JobCancelled()
        headers_map = fetch.fetch_batch_headers(conn, batch)
        snippets_map = fetch.fetch_batch_snippets(conn, batch, settings.BODY_SNIPPET_BYTES)

        records = []
        for uid in batch:
            raw_headers = headers_map.get(uid)
            if raw_headers is None:
                continue
            parsed = fetch.parse_headers(raw_headers)
            snippet_raw = snippets_map.get(uid, b'')
            snippet = fetch.clean_snippet(snippet_raw)
            message_id = parsed['message_id'] or f'<no-message-id-uid{uid}-job{job.id}@limpmail.local>'
            records.append(EmailRecord(
                job=job,
                uid=uid,
                message_id=message_id,
                from_addr=parsed['from_addr'][:998],
                subject=parsed['subject'][:998],
                date=parsed['date'][:255],
                snippet=snippet[:2000],
                classify_status='pending',
            ))

        if records:
            with DB_WRITE_LOCK:
                EmailRecord.objects.bulk_create(records, ignore_conflicts=True)


def _classify_phase(job):
    with DB_WRITE_LOCK:
        job.status = 'classifying'
        job.save(update_fields=['status', 'updated_at'])

    instruction = Instruction.objects.first()
    instruction_text = instruction.text if instruction else ''

    rate_limiter = classify.RateLimiter(settings.GEMINI_RPM, 60.0)

    while True:
        if is_cancelled(job.id):
            raise JobCancelled()
        now = timezone.now()
        candidates = list(
            EmailRecord.objects.filter(job=job)
            .filter(
                Q(classify_status='pending')
                | Q(classify_status='failed', next_retry_at__lte=now, retry_count__lt=settings.MAX_BATCH_RETRIES)
            )
            .order_by('id')[: settings.CLASSIFY_BATCH_SIZE * settings.GEMINI_MAX_WORKERS * 3]
        )

        if not candidates:
            still_waiting = EmailRecord.objects.filter(
                job=job, classify_status='failed', retry_count__lt=settings.MAX_BATCH_RETRIES
            ).exists()
            if still_waiting:
                time.sleep(5)
                continue
            break

        batches = list(fetch.chunked(candidates, settings.CLASSIFY_BATCH_SIZE))
        with ThreadPoolExecutor(max_workers=settings.GEMINI_MAX_WORKERS) as executor:
            futures = [
                executor.submit(_classify_one_batch, batch, instruction_text, rate_limiter)
                for batch in batches
            ]
            for f in futures:
                f.result()


def _classify_one_batch(batch_records, instruction_text, rate_limiter):
    items = [
        {
            'id': i,
            'from': r.from_addr,
            'subject': r.subject,
            'date': r.date,
            'snippet': r.snippet[:150],
        }
        for i, r in enumerate(batch_records)
    ]

    try:
        result_map = classify.classify_batch(items, instruction_text, rate_limiter)
    except classify.ClassificationError:
        _mark_classify_failed(batch_records)
        return

    to_update = []
    failed = []
    for i, record in enumerate(batch_records):
        category = result_map.get(i)
        if category:
            record.ai_category = category
            record.classify_status = 'done'
            record.apply_status = 'not_applicable' if category == 'IMPORTANTE' else 'pending'
            to_update.append(record)
        else:
            failed.append(record)

    with DB_WRITE_LOCK:
        if to_update:
            EmailRecord.objects.bulk_update(to_update, ['ai_category', 'classify_status', 'apply_status'])
    if failed:
        _mark_classify_failed(failed)


def _mark_classify_failed(records):
    now = timezone.now()
    for r in records:
        r.retry_count += 1
        backoff_seconds = min(2 ** r.retry_count, 300)
        r.next_retry_at = now + timedelta(seconds=backoff_seconds)
        r.classify_status = 'failed'
    with DB_WRITE_LOCK:
        EmailRecord.objects.bulk_update(records, ['retry_count', 'next_retry_at', 'classify_status'])


def _run_apply(job_id):
    job = Job.objects.get(id=job_id)
    try:
        with DB_WRITE_LOCK:
            job.status = 'applying'
            job.save(update_fields=['status', 'updated_at'])

        account = job.account
        conn = imap_pool.connect(account.host, account.port, account.email, account.password)
        try:
            imap_pool.select_inbox(conn, readonly=False)
            _apply_phase(job, account, conn)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

        with DB_WRITE_LOCK:
            job.status = 'completed'
            job.error_message = ''
            job.save(update_fields=['status', 'error_message', 'updated_at'])
    except JobCancelled:
        with DB_WRITE_LOCK:
            job.delete()
    except Exception as exc:
        with DB_WRITE_LOCK:
            job.error_message = str(exc)
            job.status = 'reviewing'
            job.save(update_fields=['error_message', 'status', 'updated_at'])
    finally:
        _unmark_running(f'apply-{job_id}')
        _clear_cancel(f'apply-{job_id}')


def _apply_phase(job, account, conn):
    all_uids = fetch.search_all_uids(conn)
    msgid_to_uid = {}
    for batch in fetch.chunked(all_uids, settings.FETCH_BATCH_SIZE):
        if is_cancelled(f'apply-{job.id}'):
            raise JobCancelled()
        headers_map = fetch.fetch_batch_message_ids(conn, batch)
        for uid, raw in headers_map.items():
            mid = fetch.extract_message_id(raw)
            if mid:
                msgid_to_uid[mid] = uid

    move_supported = imap_pool.supports_move(conn)

    pending = [
        r for r in EmailRecord.objects.filter(job=job, apply_status__in=['pending', 'failed'])
        if r.final_category in ('SPAM', 'LIXEIRA')
    ]

    groups = {'SPAM': [], 'LIXEIRA': []}
    for r in pending:
        groups[r.final_category].append(r)

    folder_map = {'SPAM': account.spam_folder, 'LIXEIRA': account.trash_folder}

    for category, records in groups.items():
        dest_folder = folder_map.get(category)
        if not records:
            continue
        if not dest_folder:
            _mark_apply_result(records, 'failed', 'pasta de destino não configurada')
            continue

        to_move = []
        to_skip = []
        for r in records:
            current_uid = msgid_to_uid.get(r.message_id)
            if current_uid is None:
                to_skip.append(r)
            else:
                to_move.append((current_uid, r))

        if to_skip:
            _mark_apply_result(to_skip, 'applied', '')

        for batch in fetch.chunked(to_move, settings.FETCH_BATCH_SIZE):
            uid_set = ','.join(str(uid) for uid, _r in batch)
            batch_records = [r for _uid, r in batch]
            try:
                if move_supported:
                    typ, data = conn.uid('move', uid_set, dest_folder)
                    if typ != 'OK':
                        raise imap_pool.ImapConnectionError(f'MOVE falhou: {data}')
                else:
                    typ, data = conn.uid('copy', uid_set, dest_folder)
                    if typ != 'OK':
                        raise imap_pool.ImapConnectionError(f'COPY falhou: {data}')
                    conn.uid('store', uid_set, '+FLAGS', '(\\Deleted)')
                    conn.expunge()
                _mark_apply_result(batch_records, 'applied', '')
            except Exception as exc:
                _mark_apply_result(batch_records, 'failed', str(exc))


def _mark_apply_result(records, status, error_message):
    for r in records:
        r.apply_status = status
        r.apply_error = error_message
    with DB_WRITE_LOCK:
        EmailRecord.objects.bulk_update(records, ['apply_status', 'apply_error'])
