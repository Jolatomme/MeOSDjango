from django.contrib import admin
from .models import OchecklistReport, OchecklistRunner, OchecklistChangeLog

@admin.register(OchecklistReport)
class OchecklistReportAdmin(admin.ModelAdmin):
    list_display = ['event', 'creator', 'created', 'received_at', 'runner_count']
    list_filter = ['created', 'received_at']
    search_fields = ['event', 'creator']
    readonly_fields = ['received_at']
    
    def runner_count(self, obj):
        return obj.runners.count()
    runner_count.short_description = 'Runners'

@admin.register(OchecklistRunner)
class OchecklistRunnerAdmin(admin.ModelAdmin):
    list_display = ['name', 'org', 'class_name', 'start_status', 'report_link', 'has_changelog']
    list_filter = ['start_status', 'class_name', 'org', 'report__created']
    search_fields = ['name', 'org', 'bib', 'runner_id']
    readonly_fields = ['report_link']
    
    def report_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        url = reverse('admin:ochecklist_ochecklistreport_change', args=[obj.report.id])
        return format_html('<a href="{}">{}</a>', url, obj.report.event)
    report_link.short_description = 'Report'
    
    def has_changelog(self, obj):
        return hasattr(obj, 'changelog')
    has_changelog.boolean = True
    has_changelog.short_description = 'Has Changelog'

@admin.register(OchecklistChangeLog)
class OchecklistChangeLogAdmin(admin.ModelAdmin):
    list_display = ['runner_name', 'dns', 'late_start', 'new_card', 'comment', 'new_runner']
    list_filter = ['dns', 'late_start', 'new_card', 'comment', 'new_runner']
    search_fields = ['runner__name', 'runner__org']
    
    def runner_name(self, obj):
        return obj.runner.name
    runner_name.short_description = 'Runner'