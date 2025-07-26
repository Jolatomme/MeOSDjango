from django.db import models
from results.models import (Mopcompetition, Mopclass, Mopcompetitor,
                           Mopclasscontrol, Mopradio, Mopcontrol,
                           Moporganization, Mopteam, Mopteammember)

from django.db import models

def update_table(table, cid, id, **kwargs):
    obj, created = table.objects.update_or_create(
        cid=cid, id=id,
        defaults=kwargs)
    return obj

def update_link_table(table, cid, id, field_name, encoded):
    table.objects.filter(cid=cid, id=id).delete()
    legs = encoded.split(';')
    for leg_index, leg in enumerate(legs, start=1):
        runners = leg.split(',')
        for ord_index, runner in enumerate(runners, start=1):
            if runner:
                table.objects.create(cid=cid, id=id, leg=leg_index,
                                     ord=ord_index, **{field_name: runner})

def clear_competition(cid):
    tables = [Control, Class, Organization, Competitor, Team, TeamMember,
              ClassControl, Radio]
    for table in tables:
        table.objects.filter(cid=cid).delete()

def process_competition(cid, cmp):
    name = cmp.get('name', '')
    date = cmp.get('date', '')
    organizer = cmp.get('organizer', '')
    homepage = cmp.get('homepage', '')
    update_table(Competition, cid, 1, name=name, date=date,
                 organizer=organizer, homepage=homepage)

def process_control(cid, ctrl):
    ctrl_id = ctrl.get('id')
    name = ctrl.get('name', '')
    update_table(Control, cid, ctrl_id, name=name)

def process_class(cid, cls):
    cls_id = cls.get('id')
    ord = cls.get('ord', '')
    name = cls.get('name', '')
    update_table(Class, cid, cls_id, name=name, ord=ord)
    if 'radio' in cls:
        radio = cls['radio']
        update_link_table(ClassControl, cid, cls_id, 'ctrl', radio)

def process_organization(cid, org):
    org_id = org.get('id')
    if org.get('delete') == 'true':
        Organization.objects.filter(cid=cid, id=org_id).delete()
        return
    name = org.get('name', '')
    update_table(Organization, cid, org_id, name=name)

def process_competitor(cid, cmp):
    base = cmp.get('base', {})
    cmp_id = cmp.get('id')
    if cmp.get('delete') == 'true':
        Competitor.objects.filter(cid=cid, id=cmp_id).delete()
        return
    name = base.get('name', '')
    org = base.get('org', 0)
    cls = base.get('cls', 0)
    stat = base.get('stat', 0)
    st = base.get('st', 0)
    rt = base.get('rt', 0)
    update_kwargs = {'name': name, 'org': org, 'cls': cls, 'stat': stat,
                     'st': st, 'rt': rt}
    if 'input' in cmp:
        input_data = cmp['input']
        it = input_data.get('it', 0)
        tstat = input_data.get('tstat', 0)
        update_kwargs.update({'it': it, 'tstat': tstat})

    update_table(Competitor, cid, cmp_id, **update_kwargs)

    if 'radio' in cmp:
        Radio.objects.filter(cid=cid, id=cmp_id).delete()
        radios = cmp['radio'].split(';')
        for radio in radios:
            tmp = radio.split(',')
            if len(tmp) == 2:
                radio_id, radio_time = tmp
                Radio.objects.create(cid=cid, id=cmp_id, ctrl=radio_id,
                                     rt=radio_time)

def process_team(cid, team):
    base = team.get('base', {})
    team_id = team.get('id')
    if team.get('delete') == 'true':
        Team.objects.filter(cid=cid, id=team_id).delete()
        return

    name = base.get('name', '')
    org = base.get('org', 0)
    cls = base.get('cls', 0)
    stat = base.get('stat', 0)
    st = base.get('st', 0)
    rt = base.get('rt', 0)

    update_table(Team, cid, team_id, name=name, org=org, cls=cls, stat=stat, 
                 st=st, rt=rt)

    if 'r' in team:
        update_link_table(TeamMember, cid, team_id, 'rid', team['r'])

