from django.db import models


class Account(models.Model):
    """Conta IMAP conectada. Linha única (singleton) — app é single-user."""

    PROVIDER_CHOICES = [
        ('custom', 'Domínio próprio'),
        ('gmail', 'Gmail'),
        ('outlook', 'Outlook'),
    ]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='custom')
    host = models.CharField(max_length=255)
    port = models.IntegerField(default=993)
    email = models.CharField(max_length=255)
    password = models.CharField(max_length=255)
    spam_folder = models.CharField(max_length=255, blank=True)
    trash_folder = models.CharField(max_length=255, blank=True)
    uid_validity = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Instruction(models.Model):
    """Bloco de regras de classificação (linguagem natural). Linha única."""

    text = models.TextField(default='')
    updated_at = models.DateTimeField(auto_now=True)


class Job(models.Model):
    STATUS_CHOICES = [
        ('discovering', 'discovering'),
        ('fetching', 'fetching'),
        ('classifying', 'classifying'),
        ('reviewing', 'reviewing'),
        ('applying', 'applying'),
        ('completed', 'completed'),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='jobs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='discovering')
    total_uids = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class EmailRecord(models.Model):
    CATEGORY_CHOICES = [
        ('IMPORTANTE', 'IMPORTANTE'),
        ('SPAN', 'SPAN'),
        ('LIXEIRA', 'LIXEIRA'),
    ]
    CLASSIFY_STATUS_CHOICES = [
        ('pending', 'pending'),
        ('done', 'done'),
        ('failed', 'failed'),
    ]
    APPLY_STATUS_CHOICES = [
        ('not_applicable', 'not_applicable'),
        ('pending', 'pending'),
        ('applied', 'applied'),
        ('skipped', 'skipped'),
        ('failed', 'failed'),
    ]

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='emails')
    uid = models.BigIntegerField(null=True, blank=True)
    message_id = models.CharField(max_length=998, db_index=True)
    from_addr = models.CharField(max_length=998, blank=True, default='')
    subject = models.CharField(max_length=998, blank=True, default='')
    date = models.CharField(max_length=255, blank=True, default='')
    snippet = models.TextField(blank=True, default='')

    ai_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, null=True, blank=True)
    user_override = models.CharField(max_length=20, choices=CATEGORY_CHOICES, null=True, blank=True)

    classify_status = models.CharField(max_length=10, choices=CLASSIFY_STATUS_CHOICES, default='pending')
    apply_status = models.CharField(max_length=20, choices=APPLY_STATUS_CHOICES, default='not_applicable')
    apply_error = models.TextField(blank=True, default='')

    batch_id = models.CharField(max_length=64, blank=True, default='')
    retry_count = models.IntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['job', 'message_id'], name='unique_message_id_per_job'),
        ]
        indexes = [
            models.Index(fields=['job', 'classify_status']),
            models.Index(fields=['job', 'apply_status']),
        ]

    @property
    def final_category(self):
        return self.user_override or self.ai_category


class SenderReputation(models.Model):
    """Placar acumulado por remetente (nome de exibicao ou dominio): quantas vezes ja foi
    classificado como IMPORTANTE / SPAN / LIXEIRA ao longo de execucoes anteriores. Sobrevive
    a resets de job (Zerar) -- e o que da a classificacao "memoria" sobre remetentes que so
    mandam porcaria (nunca IMPORTANTE) vs remetentes com historico misto."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='sender_reputations')
    sender = models.CharField(max_length=255, db_index=True)
    importante_count = models.IntegerField(default=0)
    span_count = models.IntegerField(default=0)
    lixeira_count = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['account', 'sender'], name='unique_sender_per_account'),
        ]
