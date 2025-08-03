from django.http          import Http404
from results.models import (Mopcompetition, Mopclass, Mopclasscontrol)

runnerStatus = {0:  "UKNWN",
                1:  "OK",
                3:  "MP",
                4:  "DNF",
                5:  "DSQ",
                6:  "OT",
                20: "DNS",
                21: "CANCEL",
                99: "NC"}

def formatTime(time:int):
    """ Format time from seconds
    """
    return "{0:d}:{1:02d}:{2:02d}".format(int(time/3600), int((time/60)%60),
                                          int(time%60))

def formatTimeWithMs(timeWithMs:int):
    """ Format time from seconds with 1/10 precision """
    time = timeWithMs/10
    return "{0:d}:{1:02d}:{2:02d}.{3:d}".format(time/3600, (time/60)%60, time%60, timeWithMs%10)

def formatTimeList(timeList:list, statusList:list = None):
    """ Format time from seconds or return runner status if not OK """
    return [formatTime(rt) if statusList[n] == 'OK' else statusList[n]
                for n,rt in enumerate(timeList)]

def nombreLegs (comp_id:int, cls:int = 0):
    if cls == 0:
        return len(set(Mopclasscontrol.objects.filter(cid=comp_id)\
          .values_list('leg', flat=True)))
    else:
        return len(set(Mopclasscontrol.objects.filter(cid=comp_id, id=cls)\
          .values_list('leg', flat=True)))

def categoriesList (comp_id:int):
    catListe = []
    for mClass in Mopclass.objects.filter(cid=comp_id).order_by('ord'):
        legsOfClass = sorted(set(Mopclasscontrol.objects\
          .filter(cid=comp_id, id=mClass.id).values_list('leg', flat=True)))
        catListe.append((mClass.id, mClass.name, legsOfClass))
    return catListe

def getCompetition (comp_id:int):
    try:
        return Mopcompetition.objects.get(cid=comp_id)
    except:
        raise Http404("Cette compétition n'existe pas")
