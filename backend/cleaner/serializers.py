from rest_framework import serializers

from .models import Account, EmailRecord, Instruction, Job


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ['id', 'provider', 'host', 'port', 'email', 'spam_folder', 'trash_folder', 'uid_validity', 'created_at', 'updated_at']


class InstructionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instruction
        fields = ['id', 'text', 'updated_at']


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ['id', 'account', 'status', 'total_uids', 'error_message', 'created_at', 'updated_at']


class EmailRecordSerializer(serializers.ModelSerializer):
    final_category = serializers.CharField(read_only=True)

    class Meta:
        model = EmailRecord
        fields = [
            'id', 'uid', 'message_id', 'from_addr', 'subject', 'date', 'snippet',
            'ai_category', 'user_override', 'final_category',
            'classify_status', 'apply_status', 'apply_error', 'retry_count',
        ]
