# Django imports
from django.shortcuts     import render, get_object_or_404
from django.http          import HttpResponse
from django.views.generic import ListView
from django.db.models     import Max
from django.views.decorators.csrf import csrf_exempt
# Settings
from MeOSDjango.dev_settings import MEOS_PASSWORD

# Other imports
import markdown
import xml.etree.ElementTree as ET

# Models imports
from .models          import (Mopcompetition, Mopclass, Mopteammember,
                              Mopcompetitor, Mopradio, Mopclasscontrol,
                              MeosTutorial)

#  Utility functions imports
from results.utils.database_utils import *
from results.utils.view_utils import *


# Class based views ***********************
class IndexView(ListView):
    template_name = "index.html"

    def get_queryset(self):
        """ Return the competitions """
        return Mopcompetition.objects.all().order_by("-date")


class TutoView(ListView):
    template_name = "tuto.html"

    def get_queryset(self):
        """ Return the tutorials """
        return MeosTutorial.objects.all()
# Class based views ENDS ******************

# Functions based views *******************
def ShowCategories(request, comp_id):
    categories = Mopclass.objects.filter(cid=comp_id).order_by('name')
    competition =  Mopcompetition.objects.get(cid=comp_id)
    context = {"categories": categories,
               "competition" : competition}
    return render(request, "category.html", context)

def MarkdownView(request, article_id):
    md = markdown.Markdown(extensions=["fenced_code"])
    markdown_content = MeosTutorial.objects.get(pk=article_id)
    markdown_content.content = md.convert(markdown_content.text)
    context = {"markdown_content": markdown_content}
    return render(request, "markdown_content.html",
        context=context)

def DisplayCategory(request, comp_id, cls_id):
    """ Display category details
    """
    num_legs = Mopteammember.objects.filter(cid=comp_id).\
            aggregate(Max('leg'))['leg__max']
    if (num_legs != None and num_legs > 1):
        # Relais
        results = []
        Time = []
        TimeDiff = []
    else:
        # NO Relais
        results = Mopcompetitor.objects.filter(cls=cls_id, cid=comp_id,
                                            stat__gt=0).order_by('stat',
                                                                 'rt',
                                                                 'id')
        runTime = [rt/10 for rt in results.values_list("rt", flat=True)]
        tDiff = [rt - runTime[0] for rt in runTime]
        runStatus = [runnerStatus[stat] for stat in
                     results.values_list("stat", flat=True)]
        Time = formatTimeList(runTime, runStatus)
        TimeDiff = formatTimeList(tDiff, runStatus)
    categories = Mopclass.objects.filter(cid=comp_id).order_by('name')
    selectedCat = Mopclass.objects.filter(cid=comp_id).get(id=cls_id)
    competition = Mopcompetition.objects.get(cid=comp_id)
    context = {"selectedCat": selectedCat,
               "categories" : categories,
               "competition": competition,
               "results": zip(results, Time, TimeDiff, runStatus)}
    return render(request, "catDetail2.html", context)
    #return render(request, "catDetail.html", context)

def DisplayRunDetails(request, comp_id, cls_id, run_id, leg_id=None):
    """ Display control point and time for a runner
    """
    runner = Mopcompetitor.objects.get(cid=comp_id, cls=cls_id, id=run_id)
    if leg_id == None:
        # get control points for a runner
        ctrlPointѕList = [str(c) for c in Mopclasscontrol.objects.\
                           filter(cid=comp_id, id=cls_id).\
                           order_by('ord').values_list("ctrl", flat=True)]
        ctrlPointѕList.append("Finish")
    else:
        # get control points for a runner in relay
        pass
    runRace = Mopradio.objects.filter(cid=comp_id, id=run_id).order_by('rt')
    runTime = {str(key): formatTime(value/10) for key, value
               in zip(runRace.values_list("ctrl", flat=True),
                      runRace.values_list("rt", flat=True))}
    runTime["Finish"]=formatTime(runner.rt/10)
    ctrlPointѕTime = [runTime[key] if key in runTime else "---"
                       for key in ctrlPointѕList]
    competition = Mopcompetition.objects.get(cid=comp_id)
    categories = Mopclass.objects.filter(cid=comp_id).order_by('name')
    selectedCat = Mopclass.objects.filter(cid=comp_id).get(id=cls_id)
    context={"competition": competition,
             "categories": categories,
             "category": selectedCat,
             "runner_name": runner.name.replace(','," "),
             "runner_status": runnerStatus[runner.stat],
             "ctrlPointѕ": zip(ctrlPointѕList, ctrlPointѕTime)
            }
    return render(request, "circuitDetail.html", context)

def test1(request):
    return render(request, "test_template1.html", None)

def test2(request):
    return render(request, "test_template2.html", None)

def test3(request):
    return render(request, "test_template3.html", None)

# Update Race database with MeOS Online Protocol
@csrf_exempt
def update_database(request):
    password = request.headers.get('HTTP_PWD')
    cmp_id = request.headers.get('HTTP_COMPETITION')

    if not cmp_id or int(cmp_id) <= 0:
        return HttpResponse('BADCMP', status=400)

    if password != MEOS_PASSWORD:
        return HttpResponse('BADPWD', status=401)

    data = request.body
    if data.startswith(b'PK'):
        return HttpResponse('NOZIP', status=400)

    try:
        update = ET.fromstring(data)
    except ET.ParseError:
        return HttpResponse('Invalid XML', status=400)

    if update.tag == "MOPComplete":
        clear_competition(cmp_id)
    elif update.tag != "MOPDiff":
        return HttpResponse('Unknown data', status=400)

    for element in update:
        if element.tag == "cmp":
            process_competitor(cmp_id, element)
        elif element.tag == "tm":
            process_team(cmp_id, element)
        elif element.tag == "cls":
            process_class(cmp_id, element)
        elif element.tag == "org":
            process_organization(cmp_id, element)
        elif element.tag == "ctrl":
            process_control(cmp_id, element)
        elif element.tag == "competition":
            process_competition(cmp_id, element)

    return HttpResponse('OK')

# Functions based views ENDS ***************
