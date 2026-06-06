from django.db import models

class OchecklistReport(models.Model):
    """Stores metadata from O'checklist YAML report"""
    version = models.CharField(max_length=10)
    creator = models.CharField(max_length=100)
    created = models.DateTimeField()
    event = models.CharField(max_length=200, blank=True, null=True)
    received_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created']
        verbose_name = "O'checklist Report"
        verbose_name_plural = "O'checklist Reports"

class OchecklistRunner(models.Model):
    """Stores individual runner data from O'checklist report"""
    STATUS_CHOICES = [
        ('Started OK', 'Started OK'),
        ('DNS', 'DNS'),
        ('Late start', 'Late start'),
    ]
    
    report = models.ForeignKey(OchecklistReport, on_delete=models.CASCADE, related_name='runners')
    runner_id = models.CharField(max_length=50, blank=True, null=True)  # IOF xml person id
    bib = models.CharField(max_length=20, blank=True, null=True)
    name = models.CharField(max_length=100)
    org = models.CharField(max_length=100)
    card_number = models.CharField(max_length=20, blank=True, null=True)
    start_time = models.DateTimeField(blank=True, null=True)  # ISO 8601 or time only
    class_name = models.CharField(max_length=50)
    start_status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    new_card = models.CharField(max_length=20, blank=True, null=True)
    comment = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['start_time']
        verbose_name = "O'checklist Runner"
        verbose_name_plural = "O'checklist Runners"

class OchecklistChangeLog(models.Model):
    """Stores timestamped status changes"""
    runner = models.OneToOneField(OchecklistRunner, on_delete=models.CASCADE, related_name='changelog')
    dns = models.DateTimeField(blank=True, null=True)
    late_start = models.DateTimeField(blank=True, null=True)
    new_card = models.DateTimeField(blank=True, null=True)
    comment = models.DateTimeField(blank=True, null=True)
    new_runner = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        verbose_name = "O'checklist Change Log"
        verbose_name_plural = "O'checklist Change Logs"