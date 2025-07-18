# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the
#     desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create,
#     modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field
# names.
from django.db import models


class Mopcompetition(models.Model):
    """ Competitions
    """
    # The composite primary key (cid, id) found, that is not supported. The
    # first column is selected.
    cid = models.IntegerField(primary_key=True)
    id = models.IntegerField()
    name = models.CharField(verbose_name='competition', max_length=64)
    date = models.DateField()
    organizer = models.CharField(max_length=64)
    homepage = models.CharField(max_length=128)

    class Meta:
        managed = False
        db_table = 'mopCompetition'
        unique_together = (('cid', 'id'),)
        verbose_name = 'competition'
        verbose_name_plural = 'competitions'

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("Mopcompetition_detail", args=[str(self.id)])


class Mopclass(models.Model):
    """ Category
    """
    # The composite primary key (cid, id) found, that is not supported. The
    # first column is selected.
    cid = models.IntegerField(primary_key=True)
    id = models.IntegerField()
    name = models.CharField(verbose_name='category', max_length=64)
    ord = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'mopClass'
        unique_together = (('cid', 'id'),)
        verbose_name = 'category'
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("Mopclass_detail", args=[str(self.id)])


class Mopcompetitor(models.Model):
    """ Runner description
    """
    # The composite primary key (cid, id) found, that is not supported. The
    # first column is selected.
    cid = models.IntegerField(primary_key=True)
    id = models.IntegerField()
    name = models.CharField(max_length=64)
    org = models.IntegerField()
    cls = models.IntegerField()
    stat = models.IntegerField()
    st = models.IntegerField()
    rt = models.IntegerField()
    tstat = models.IntegerField()
    it = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'mopCompetitor'
        unique_together = (('cid', 'id'),)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("Mopcompetitor_detail", args=[str(self.id)])


class Mopclasscontrol(models.Model):
    # The composite primary key (cid, id, leg, ord) found, that is not
    # supported. The first column is selected.
    cid = models.IntegerField(primary_key=True)
    id = models.IntegerField()
    leg = models.IntegerField()
    ord = models.IntegerField()
    ctrl = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'mopClassControl'
        unique_together = (('cid', 'id', 'leg', 'ord'),)


class Mopradio(models.Model):
    # The composite primary key (cid, id, ctrl) found, that is not supported.
    # The first column is selected.
    cid = models.IntegerField(primary_key=True)
    id = models.IntegerField()
    ctrl = models.IntegerField()
    rt = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'mopRadio'
        unique_together = (('cid', 'id', 'ctrl'),)


class Mopcontrol(models.Model):
    # The composite primary key (cid, id) found, that is not supported. The
    # first column is selected.
    cid = models.IntegerField(primary_key=True)
    id = models.IntegerField()
    name = models.CharField(max_length=64)

    class Meta:
        managed = False
        db_table = 'mopControl'
        unique_together = (('cid', 'id'),)


class Moporganization(models.Model):
    # The composite primary key (cid, id) found, that is not supported. The
    # first column is selected.
    cid = models.IntegerField(primary_key=True)
    id = models.IntegerField()
    name = models.CharField(max_length=64)

    class Meta:
        managed = False
        db_table = 'mopOrganization'
        unique_together = (('cid', 'id'),)


class Mopteam(models.Model):
    # The composite primary key (cid, id) found, that is not supported. The
    # first column is selected.
    cid = models.IntegerField(primary_key=True)
    id = models.IntegerField()
    name = models.CharField(max_length=64)
    org = models.IntegerField()
    cls = models.IntegerField()
    stat = models.IntegerField()
    st = models.IntegerField()
    rt = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'mopTeam'
        unique_together = (('cid', 'id'),)


class Mopteammember(models.Model):
    # The composite primary key (cid, id, leg, ord) found, that is not
    # supported. The first column is selected.
    cid = models.IntegerField(primary_key=True)
    id = models.IntegerField()
    leg = models.IntegerField()
    ord = models.IntegerField()
    rid = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'mopTeamMember'
        unique_together = (('cid', 'id', 'leg', 'ord'),)

class MeosTutorial(models.Model):
    title = models.CharField(max_length=256)
    text = models.TextField()

    class Meta:
        verbose_name_plural = "Markdown content"

    def __str__(self):
        return self.title
