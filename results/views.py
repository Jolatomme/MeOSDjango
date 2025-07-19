# Django imports
from django.shortcuts     import render, get_object_or_404
from django.http          import HttpResponse
from django.views.generic import ListView
from django.db.models     import Max

# Other imports
import markdown

# Models imports
from .models          import (Mopcompetition, Mopclass, Mopteammember,
                              Mopcompetitor, Mopradio, Mopclasscontrol,
                              MeosTutorial)


# Helper functions ************************
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

def formatTimeList(timeList:list, statusList:list = None):
    """ Format time from seconds
    """
    return [formatTime(rt) if statusList[n] == 'OK' else statusList[n]
                for n,rt in enumerate(timeList)]

# Helper functions ENDS *******************

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
               "results": zip(results, Time, TimeDiff)}
    return render(request, "catDetail.html", context)

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
        # DEBUG Prints
        #print("{0} {1} -> Status: {2} ".format(runner.name.replace(','," "),
        #                              runner.org,
        #                              runnerStatus[runner.stat]))
        #print(ctrlPointѕList)
    else:
        # get control points for a runner in relay
        pass
    runRace = Mopradio.objects.filter(cid=comp_id, id=run_id).order_by('rt')
    runTime = {str(key): formatTime(value/10) for key, value
               in zip(runRace.values_list("ctrl", flat=True),
                      runRace.values_list("rt", flat=True))}
    runTime["Finish"]=formatTime(runner.rt/10)
    #print(runTime)
    ctrlPointѕTime = [runTime[key] if key in runTime else "---" for key in ctrlPointѕList]
    #print(ctrlPointѕTime)
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

def etiquettes(request):
    return render(request, "etiquettes.html", None)

def drivers(request):
    return render(request, "drivers.html", None)

# Functions based views ENDS ***************

#def index(request):
#    if 'competition' in request.GET:
#        request.session['competition'] = int(request.GET['competition'])
#
#    cmp_id = request.session.get('competition', 0)
#
#    if 'select' in request.GET or cmp_id == 0:
#        competitions = Mopcompetition.objects.all().order_by('-date')
#        return render(request, 'results/select_competition.html', {'competitions': competitions})
#
#    competition = get_object_or_404(Mopcompetition, id=cmp_id)
#    classes = Mopclass.objects.filter(cid=cmp_id).order_by('ord')
#
#    context = {
#        'competition': competition,
#        'classes': classes,
#    }
#
#    if 'cls' in request.GET:
#        cls_id = int(request.GET['cls'])
#        cls = get_object_or_404(Class, id=cls_id)
#        context['class'] = cls
#
#        num_legs = TeamMember.objects.filter(cid=cmp_id, id__cls=cls_id).aggregate(Max('leg'))['leg__max']
#        context['num_legs'] = num_legs
#
#        if num_legs > 1:
#            leg = int(request.GET.get('leg', 1))
#            ord = int(request.GET.get('ord', 1))
#            radio = request.GET.get('radio')
#
#            if radio:
#                if radio == 'finish':
#                    results = Competitor.objects.filter(
#                        tm__cid=cmp_id, tm__id__cls=cls_id, tm__leg=leg, tm__ord=ord, stat__gt=0
#                    ).order_by('stat', 'rt', 'id')
#                    context['rname'] = 'Finish'
#                else:
#                    rid = int(radio)
#                    control = get_object_or_404(Control, id=rid)
#                    context['rname'] = control.name
#                    results = Radio.objects.filter(
#                        ctrl=rid, id__tm__cid=cmp_id, id__tm__id__cls=cls_id, id__tm__leg=leg, id__tm__ord=ord, id__stat__lte=1
#                    ).order_by('rt')
#
#                context['results'] = results
#
#        else:
#            radio = request.GET.get('radio')
#            if radio:
#                if radio == 'finish':
#                    results = Competitor.objects.filter(
#                        cls=cls_id, cid=cmp_id, stat__gt=0
#                    ).order_by('stat', 'rt', 'id')
#                    context['rname'] = 'Finish'
#                else:
#                    rid = int(radio)
#                    control = get_object_or_404(Control, id=rid)
#                    context['rname'] = control.name
#                    results = Radio.objects.filter(
#                        ctrl=rid, id__cls=cls_id, id__cid=cmp_id, id__stat__lte=1
#                    ).order_by('rt')
#
#                context['results'] = results
#
#    return render(request, 'results/index.html', context)
