import datetime
import zlib
import hashlib
import base64
import yaml
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import render, get_object_or_404, redirect
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.utils.translation import ngettext
from .models import OchecklistReport, OchecklistRunner, OchecklistChangeLog

# Statuts envoyés par l'application O'checklist (rapport YAML v1.5/v1.6).
VALID_START_STATUSES = {'Started OK', 'DNS', 'Late start'}

# Clés du ChangeLog reconnues par le modèle. Sert à ne pas créer une ligne
# vide quand l'application n'envoie qu'un champ inconnu.
CHANGELOG_KEYS = ('TickedOff', 'DNS', 'LateStart', 'NewCard', 'Comment', 'NewRunner')


def validate_runner_entry(runner_data, index):
    """Validate one ``Data[]`` entry from an O'checklist report.

    Returns an error message (str) or None when the entry is usable. The
    Android app always sends these fields, but a malformed body must produce
    a 400 instead of a 500 from the database layer.
    """
    position = index + 1
    if not isinstance(runner_data, dict):
        return f'Invalid runner entry #{position}: expected a mapping'

    runner = runner_data.get('Runner')
    if not isinstance(runner, dict):
        return f'Invalid runner entry #{position}: missing Runner mapping'

    for field in ('Name', 'StartStatus'):
        value = runner.get(field)
        if not isinstance(value, str):
            return f'Invalid runner entry #{position}: missing {field}'

    if not runner['StartStatus'].strip():
        return f'Invalid runner entry #{position}: missing StartStatus'

    if runner['StartStatus'] not in VALID_START_STATUSES:
        return (
            f'Invalid runner entry #{position}: unsupported StartStatus '
            f'"{runner["StartStatus"]}"'
        )

    changelog = runner_data.get('ChangeLog')
    if changelog is not None and not isinstance(changelog, dict):
        return f'Invalid runner entry #{position}: ChangeLog must be a mapping'

    return None


# Taille maximale du corps décompressé (alignée sur
# DATA_UPLOAD_MAX_MEMORY_SIZE) : borne les bombes gzip.
MAX_DECOMPRESSED_SIZE = 10 * 1024 * 1024


def decompress_if_needed(request_body, content_encoding_header, max_size=None):
    """Decompress request body if Content-Encoding indicates gzip.

    Returns the original body when the encoding is absent, unsupported or
    invalid. Returns ``None`` when the decompressed payload exceeds
    ``max_size`` (default: ``MAX_DECOMPRESSED_SIZE``).
    """
    if not content_encoding_header:
        return request_body

    content_encoding = content_encoding_header.lower()

    # Check for gzip encoding
    if 'gzip' in content_encoding:
        if max_size is None:
            max_size = MAX_DECOMPRESSED_SIZE
        try:
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            decompressed = decompressor.decompress(request_body, max_size + 1)
            # unconsumed_tail means more output is pending: too large.
            if len(decompressed) > max_size or decompressor.unconsumed_tail:
                return None
            return decompressed + decompressor.flush()
        except zlib.error:
            # If decompression fails, return original body (might not actually be gzipped)
            return request_body

    # Could add support for other encodings like deflate here if needed
    return request_body

def verify_content_digest(request_body, content_digest_header):
    """Verify the Content-Digest header against the request body"""
    if not content_digest_header:
        # If no header is provided, we might still accept it depending on security requirements
        return True
    
    try:
        # Parse header format: e.g., "sha-256=:base64value:" or "sha-256=base64value"
        content_digest_header = content_digest_header.strip()
        
        if '=' not in content_digest_header:
            return False
            
        algo_part, value_part = content_digest_header.split('=', 1)
        algo_part = algo_part.strip().lower()
        value_part = value_part.strip()
        
        # Handle possible colons around base64 value (RFC 3230 style)
        if value_part.startswith(':') and value_part.endswith(':'):
            value_part = value_part[1:-1]
        
        # Determine hash algorithm
        if algo_part in ['sha-256', 'sha256']:
            hash_algo = hashlib.sha256
        elif algo_part in ['sha-512', 'sha512']:
            hash_algo = hashlib.sha512
        elif algo_part in ['md5']:
            hash_algo = hashlib.md5
        else:
            return False  # Unsupported algorithm
        
        # Compute hash of request body
        computed_hash = hash_algo(request_body).digest()
        
        # Decode the provided value (could be base64 or hex)
        try:
            # Try base64 first
            provided_hash = base64.b64decode(value_part)
        except Exception:
            try:
                # Try hex
                provided_hash = bytes.fromhex(value_part)
            except Exception:
                return False  # Not valid base64 or hex
        
        # Compare hashes securely
        return computed_hash == provided_hash
        
    except Exception:
        return False

@csrf_exempt
@require_POST
def ochecklist_update(request):
    """Endpoint to receive O'checklist YAML data via HTTP POST"""
    
    # Optional security header authentication (separate from checksum)
    security_header_key = getattr(settings, 'OCHECKLIST_HEADER_KEY', '')
    security_header_value = getattr(settings, 'OCHECKLIST_HEADER_VALUE', '')
    
    if security_header_key and security_header_value:
        provided_value = request.META.get(f'HTTP_{security_header_key.upper().replace("-", "_")}', '')
        if provided_value != security_header_value:
            return HttpResponse('Unauthorized', status=401)
    
    # Verify Content-Digest checksum against original request body (before decompression)
    content_digest_header = request.META.get('HTTP_CONTENT_DIGEST', '')
    if not verify_content_digest(request.body, content_digest_header):
        return HttpResponse('Invalid Content-Digest', status=400)
    
    # Handle gzip compression if present (decompress AFTER digest verification)
    content_encoding_header = request.META.get('HTTP_CONTENT_ENCODING', '')
    processed_body = decompress_if_needed(request.body, content_encoding_header)
    if processed_body is None:
        return HttpResponse('Payload too large', status=413)
    
    # Parse YAML data
    try:
        yaml_data = yaml.safe_load(processed_body.decode('utf-8'))
    except UnicodeDecodeError:
        return HttpResponse('Invalid encoding: UTF-8 required', status=400)
    except yaml.YAMLError as e:
        return HttpResponse(f'Invalid YAML: {str(e)}', status=400)
    
    # Validate required structure
    if not isinstance(yaml_data, dict) or 'Data' not in yaml_data:
        return HttpResponse("Invalid O'checklist report format", status=400)
    if not isinstance(yaml_data['Data'], list):
        return HttpResponse(
            "Invalid O'checklist report format: Data must be a list",
            status=400,
        )
    for index, runner_data in enumerate(yaml_data['Data']):
        error = validate_runner_entry(runner_data, index)
        if error:
            return HttpResponse(error, status=400)
    
    # Helper: convert YAML values to types suitable for Django ORM
    def to_str(val):
        if val is None:
            return None
        if isinstance(val, datetime.datetime):
            return val.isoformat()
        return str(val)
    
    def to_datetime(val):
        if val is None:
            return None
        if isinstance(val, datetime.datetime):
            if val.tzinfo is None:
                return timezone.make_aware(val)
            return val
        if isinstance(val, bool):
            return None
        if isinstance(val, str):
            if not val:
                return None
            try:
                dt = datetime.datetime.fromisoformat(val)
                if dt.tzinfo is None:
                    return timezone.make_aware(dt)
                return dt
            except ValueError:
                pass
            parts = val.strip().split(':')
            if len(parts) in (2, 3) and all(p.isdigit() for p in parts):
                h, m, s = int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) == 3 else 0
                if 0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60:
                    return timezone.make_aware(datetime.datetime(2000, 1, 1, h, m, s))
            return None
        if isinstance(val, (int, float)):
            total_seconds = int(val) % 86400
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            naive = datetime.datetime(2000, 1, 1, hours, minutes, seconds)
            return timezone.make_aware(naive)
        return None
    
    event_name = to_str(yaml_data.get('Event'))
    created = to_datetime(yaml_data.get('Created'))
    if created is None:
        return HttpResponse(
            "Invalid O'checklist report format: missing or invalid Created",
            status=400,
        )

    with transaction.atomic():
        # Find or create report for this event
        if event_name:
            report = OchecklistReport.objects.filter(event=event_name).order_by('-created').first()
            if report:
                report.version = to_str(yaml_data.get('Version', ''))
                report.creator = to_str(yaml_data.get('Creator', ''))
                report.created = created
                report.save()
            else:
                report = OchecklistReport.objects.create(
                    version=to_str(yaml_data.get('Version', '')),
                    creator=to_str(yaml_data.get('Creator', '')),
                    created=created,
                    event=event_name
                )
        else:
            report = OchecklistReport.objects.create(
                version=to_str(yaml_data.get('Version', '')),
                creator=to_str(yaml_data.get('Creator', '')),
                created=created,
                event=None
            )

        # Process runners — upsert by runner_id, then bib, then name
        for runner_data in yaml_data['Data']:
            runner_section = runner_data.get('Runner', {})
            changelog_data = runner_data.get('ChangeLog') or {}

            name = to_str(runner_section.get('Name', ''))
            runner_id = to_str(runner_section.get('Id'))
            bib = to_str(runner_section.get('Bib'))

            existing = None
            if runner_id:
                existing = report.runners.filter(runner_id=runner_id).first()
            if not existing and bib:
                existing = report.runners.filter(bib=bib).first()
            if not existing and name:
                existing = report.runners.filter(name=name).first()

            if existing:
                # Only update fields that are present in the incoming YAML
                if 'Id' in runner_section:
                    existing.runner_id = to_str(runner_section['Id'])
                if 'Bib' in runner_section:
                    existing.bib = to_str(runner_section['Bib'])
                if 'Name' in runner_section:
                    existing.name = to_str(runner_section['Name'])
                if 'Org' in runner_section:
                    existing.org = to_str(runner_section['Org'])
                if 'Card' in runner_section:
                    existing.card_number = to_str(runner_section['Card'])
                if 'StartTime' in runner_section:
                    existing.start_time = to_datetime(runner_section['StartTime'])
                if 'StartType' in runner_section:
                    existing.start_type = to_str(runner_section['StartType'])
                if 'ClassName' in runner_section:
                    existing.class_name = to_str(runner_section['ClassName'])
                if 'StartStatus' in runner_section:
                    existing.start_status = to_str(runner_section['StartStatus'])
                if 'NewCard' in runner_section:
                    existing.new_card = to_str(runner_section['NewCard'])
                if 'Comment' in runner_section:
                    existing.comment = to_str(runner_section['Comment'])
                existing.save()
                runner = existing

                if any(changelog_data.get(key) for key in CHANGELOG_KEYS):
                    changelog, _ = OchecklistChangeLog.objects.get_or_create(runner=runner)
                    if 'TickedOff' in changelog_data:
                        changelog.ticked_off = to_datetime(changelog_data['TickedOff'])
                    if 'DNS' in changelog_data:
                        changelog.dns = to_datetime(changelog_data['DNS'])
                    if 'LateStart' in changelog_data:
                        changelog.late_start = to_datetime(changelog_data['LateStart'])
                    if 'NewCard' in changelog_data:
                        changelog.new_card = to_datetime(changelog_data['NewCard'])
                    if 'Comment' in changelog_data:
                        changelog.comment = to_datetime(changelog_data['Comment'])
                    if 'NewRunner' in changelog_data:
                        changelog.new_runner = to_datetime(changelog_data['NewRunner'])
                    changelog.save()
            else:
                runner = OchecklistRunner.objects.create(
                    report=report,
                    runner_id=runner_id,
                    bib=bib,
                    name=name,
                    org=to_str(runner_section.get('Org', '')),
                    card_number=to_str(runner_section.get('Card')),
                    start_time=to_datetime(runner_section.get('StartTime')),
                    start_type=to_str(runner_section.get('StartType')),
                    class_name=to_str(runner_section.get('ClassName', '')),
                    start_status=to_str(runner_section.get('StartStatus', '')),
                    new_card=to_str(runner_section.get('NewCard')),
                    comment=to_str(runner_section.get('Comment'))
                )

                if any(changelog_data.get(key) for key in CHANGELOG_KEYS):
                    OchecklistChangeLog.objects.create(
                        runner=runner,
                        ticked_off=to_datetime(changelog_data.get('TickedOff')),
                        dns=to_datetime(changelog_data.get('DNS')),
                        late_start=to_datetime(changelog_data.get('LateStart')),
                        new_card=to_datetime(changelog_data.get('NewCard')),
                        comment=to_datetime(changelog_data.get('Comment')),
                        new_runner=to_datetime(changelog_data.get('NewRunner'))
                    )

    return HttpResponse('OK', status=200, content_type='text/plain')

def report_list(request):
    """Display list of all received O'checklist reports"""
    reports = OchecklistReport.objects.all()
    return render(request, 'ochecklist/report_list.html', {'reports': reports})

def clear_reports(request):
    """Delete selected reports"""
    if request.method != 'POST':
        return redirect('ochecklist_report_list')
    report_ids = request.POST.getlist('report_ids')
    if report_ids:
        deleted, _ = OchecklistReport.objects.filter(id__in=report_ids).delete()
        messages.success(request, ngettext(
            '%(n)s rapport supprimé.', '%(n)s rapports supprimés.', deleted,
        ) % {'n': deleted})
    return redirect('ochecklist_report_list')

def report_detail(request, report_id):
    """Display detailed view of a specific report with all runners"""
    report = get_object_or_404(OchecklistReport, id=report_id)
    sort = request.GET.get('sort', '')
    runners_qs = report.runners.all().select_related('changelog')
    if sort == 'status':
        runners_qs = runners_qs.order_by('start_status')
    elif sort == '-status':
        runners_qs = runners_qs.order_by('-start_status')
    elif sort == 'card':
        runners_qs = runners_qs.order_by('-new_card')
    elif sort == '-card':
        runners_qs = runners_qs.order_by('new_card')
    else:
        runners_qs = runners_qs.order_by('start_time', 'name')
    runners = list(runners_qs)
    return render(request, 'ochecklist/report_detail.html', {
        'report': report,
        'runners': runners,
        'current_sort': sort,
        'started_ok_count': report.runners.filter(start_status='Started OK').count(),
        'dns_count': report.runners.filter(start_status='DNS').count(),
        'late_start_count': report.runners.filter(start_status='Late start').count(),
        'new_card_count': report.runners.exclude(new_card='').exclude(new_card__isnull=True).count(),
    })

def runner_detail(request, runner_id):
    """Display detailed view of a specific runner"""
    runner = get_object_or_404(OchecklistRunner, id=runner_id)
    return render(request, 'ochecklist/runner_detail.html', {'runner': runner})