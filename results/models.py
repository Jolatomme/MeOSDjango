# Modèles Django mappés sur la base de données MeOS (tables mop*)
# managed = False : Django ne touche pas au schéma, MeOS en reste propriétaire.

from django.db import models


# ─── Codes statut MeOS ─────────────────────────────────────────────
STAT_UNKNOWN = 0
STAT_OK      = 1
STAT_NT      = 2
STAT_MP      = 3
STAT_DNF     = 4
STAT_DQ      = 5
STAT_OT      = 6
STAT_OCC     = 15   # Out-of-competition (v3.7)
STAT_DNS     = 20
STAT_CANCEL  = 21
STAT_NP      = 99

STATUS_LABELS = {
    STAT_UNKNOWN: ('Inconnu',         'info'),
    STAT_OK:      ('OK',              'success'),
    STAT_NT:      ('No Timing',       'info'),
    STAT_MP:      ('PM',              'danger'),
    STAT_DNF:     ('Abandon',         'warning'),
    STAT_DQ:      ('DSQ',             'danger'),
    STAT_OT:      ('H.T.',            'warning'),
    STAT_OCC:     ('Hors compét.',    'info'),
    STAT_DNS:     ('Non partant',     'secondary'),
    STAT_CANCEL:  ('Cancel',          'info'),
    STAT_NP:      ('Non participant', 'secondary'),
}


class Mopcompetition(models.Model):
    cid       = models.IntegerField(primary_key=True)
    id        = models.IntegerField()
    name      = models.CharField(verbose_name='competition', max_length=64)
    date      = models.DateField()
    organizer = models.CharField(max_length=64)
    homepage  = models.CharField(max_length=128)

    class Meta:
        managed         = False
        db_table        = 'mopCompetition'
        unique_together = (('cid', 'id'),)
        verbose_name        = 'compétition'
        verbose_name_plural = 'compétitions'
        ordering = ['-date']

    def __str__(self):
        return self.name


class Mopclass(models.Model):
    cid  = models.IntegerField(primary_key=True)
    id   = models.IntegerField()
    name = models.CharField(verbose_name='category', max_length=64)
    ord  = models.IntegerField()

    class Meta:
        managed         = False
        db_table        = 'mopClass'
        unique_together = (('cid', 'id'),)
        ordering = ['ord', 'name']

    def __str__(self):
        return self.name


class Moporganization(models.Model):
    cid  = models.IntegerField(primary_key=True)
    id   = models.IntegerField()
    name = models.CharField(max_length=64)

    class Meta:
        managed         = False
        db_table        = 'mopOrganization'
        unique_together = (('cid', 'id'),)
        ordering = ['name']

    def __str__(self):
        return self.name


class Mopcompetitor(models.Model):
    """
    st  = heure départ (secondes depuis minuit)
    rt  = temps de course (secondes ; -1 si non classé)
    it  = heure arrivée (secondes depuis minuit)
    org = id mopOrganization
    cls = id mopClass
    """
    cid   = models.IntegerField(primary_key=True)
    id    = models.IntegerField()
    name  = models.CharField(max_length=64)
    org   = models.IntegerField()
    cls   = models.IntegerField()
    stat  = models.IntegerField()
    st    = models.IntegerField()
    rt    = models.IntegerField()
    tstat = models.IntegerField()
    it    = models.IntegerField()

    class Meta:
        managed         = False
        db_table        = 'mopCompetitor'
        unique_together = (('cid', 'id'),)

    def __str__(self):
        return self.name

    @property
    def is_ok(self):
        return self.stat == STAT_OK and self.rt > 0

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.stat, ('?', 'secondary'))[0]

    @property
    def status_badge(self):
        return STATUS_LABELS.get(self.stat, ('?', 'secondary'))[1]


class Mopcontrol(models.Model):
    cid  = models.IntegerField(primary_key=True)
    id   = models.IntegerField()
    name = models.CharField(max_length=64)

    class Meta:
        managed         = False
        db_table        = 'mopControl'
        unique_together = (('cid', 'id'),)

    def __str__(self):
        return self.name


class Mopclasscontrol(models.Model):
    cid  = models.IntegerField(primary_key=True)
    id   = models.IntegerField()
    leg  = models.IntegerField()
    ord  = models.IntegerField()
    ctrl = models.IntegerField()

    class Meta:
        managed         = False
        db_table        = 'mopClassControl'
        unique_together = (('cid', 'id', 'leg', 'ord'),)
        ordering        = ['ord']


class Mopradio(models.Model):
    cid  = models.IntegerField(primary_key=True)
    id   = models.IntegerField()
    ctrl = models.IntegerField()
    rt   = models.IntegerField()

    class Meta:
        managed         = False
        db_table        = 'mopRadio'
        unique_together = (('cid', 'id', 'ctrl'),)
        ordering        = ['id', 'rt']


class Mopteam(models.Model):
    cid  = models.IntegerField(primary_key=True)
    id   = models.IntegerField()
    name = models.CharField(max_length=64)
    org  = models.IntegerField()
    cls  = models.IntegerField()
    stat = models.IntegerField()
    st   = models.IntegerField()
    rt   = models.IntegerField()

    class Meta:
        managed         = False
        db_table        = 'mopTeam'
        unique_together = (('cid', 'id'),)


class Mopteammember(models.Model):
    cid = models.IntegerField(primary_key=True)
    id  = models.IntegerField()
    leg = models.IntegerField()
    ord = models.IntegerField()
    rid = models.IntegerField()

    class Meta:
        managed         = False
        db_table        = 'mopTeamMember'
        unique_together = (('cid', 'id', 'leg', 'ord'),)


class MeosTutorial(models.Model):
    title = models.CharField(max_length=256)
    text  = models.TextField()

    class Meta:
        verbose_name_plural = 'Markdown content'

    def __str__(self):
        return self.title


# ─── Utilitaire ─────────────────────────────────────────────────────

def format_time(time_with_ms: int) -> str:
    """Format time from seconds with 1/10 precision.

    Args:
        time_with_ms: Time in units of 1/10 seconds
        (e.g., 36615 for 10h0m6.5s).

    Returns:
        Formatted time string in the format "HH:MM:SS.d", "MM:SS.d",
        "HH:MM:SS", or "MM:SS".
    """
    time_with_ms = int(time_with_ms)  # coerce float → int
    if time_with_ms < 0:
        raise ValueError("Time cannot be negative.")

    tenths = time_with_ms % 10
    total_seconds = time_with_ms // 10
    hours, remaining_seconds = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remaining_seconds, 60)

    if hours > 0:
        time_str = f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        time_str = f"{minutes:02d}:{seconds:02d}"
    if tenths != 0:
        time_str += f".{tenths}"

    return time_str
