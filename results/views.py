# Django imports
from django.shortcuts     import render, get_object_or_404
from django.http          import HttpResponse
from django.views.generic import ListView
from django.db.models     import Max

# Other imports
import markdown

# Models imports
from .models import (Mopcompetition, Mopclass, Mopteammember, Mopteam, Mopcontrol,
                    Mopcompetitor, Mopradio, Mopclasscontrol, Moporganization,
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
    """ Format time from seconds """
    return "{0:d}:{1:02d}:{2:02d}".format(int(time/3600), int((time/60)%60), int(time%60))

def formatTimeWithMs(timeWithMs:int):
    """ Format time from seconds with 1/10 precision """
    time = timeWithMs/10
    return "{0:d}:{1:02d}:{2:02d}.{3:d}".format(time/3600, (time/60)%60, time%60, timeWithMs%10)

def formatTimeList(timeList:list, statusList:list = None):
    """ Format time from seconds """
    return [formatTime(rt) if statusList[n] == 'OK' else statusList[n]
        for n,rt in enumerate(timeList)] #???

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
    """ Display category details """
    num_legs = Mopteammember.objects.filter(cid=comp_id).aggregate(Max('leg'))['leg__max']
    if (num_legs != None and num_legs > 1):
        # Relais
        results = Mopteam.objects.filter(cid=comp_id, cls=cls_id, stat__gt=0)\
        	.order_by('stat', 'rt', 'id')
        runTime = [rt/10 for rt in results.values_list("rt", flat=True)]
        tDiff = [rt - runTime[0] for rt in runTime]
        runStatus = [runnerStatus[stat] for stat in results.values_list("stat", flat=True)]
        Time = formatTimeList(runTime, runStatus)
        TimeDiff = formatTimeList(tDiff, runStatus)
        Club = [Moporganization.objects.get(id=org, cid=comp_id).name if org != 0 else ''\
        	for org in results.values_list("org", flat=True)]

    else:
        # NO Relais
        results = Mopcompetitor.objects.filter(cls=cls_id, cid=comp_id, stat__gt=0)\
        		.order_by('stat', 'rt', 'id')
        runTime = [rt/10 for rt in results.values_list("rt", flat=True)]
        tDiff = [rt - runTime[0] for rt in runTime]
        runStatus = [runnerStatus[stat] for stat in results.values_list("stat", flat=True)]
        Time = formatTimeList(runTime, runStatus)
        TimeDiff = formatTimeList(tDiff, runStatus)
        Club = [Moporganization.objects.get(id=org, cid=comp_id).name if org != 0 else ''\
        	for org in results.values_list("org", flat=True)]

    categories = Mopclass.objects.filter(cid=comp_id).order_by('name')
    selectedCat = Mopclass.objects.filter(cid=comp_id).get(id=cls_id)
    competition = Mopcompetition.objects.get(cid=comp_id)
    context = {"selectedCat": selectedCat,
               "categories" : categories,
               "competition": competition,
               "results": zip(results, Time, TimeDiff, Club)}
    return render(request, "catDetail.html", context)

def DisplayRunDetails(request, comp_id, cls_id, run_id, leg_id=None):
    """ Display control point and time for a runner or a team """

    competition = Mopcompetition.objects.get(cid=comp_id)
    categories = Mopclass.objects.filter(cid=comp_id).order_by('name')
    selectedCat = Mopclass.objects.filter(cid=comp_id).get(id=cls_id) # categories.get(id=cls_id) ?
    num_legs = Mopteammember.objects.filter(cid=comp_id).aggregate(Max('leg'))['leg__max']

    if (num_legs != None and num_legs > 1):
        # pb : meos se prend les pieds dans le tapis avec la liste des controles pour les relais
        # cette version fonctionne mais ne montre pas les postes manquants quand il y a un PM

        team = Mopteam.objects.get(cid=comp_id, cls=cls_id, id=run_id)
        # get runner list for this team
        teamMember = Mopteammember.objects.filter(cid=comp_id, id=team.id).order_by('leg')
        members = [ Mopcompetitor.objects.get(cid=comp_id, id=tm.rid) for tm in teamMember ]

        # control points for each runner in a global list
        ctrlPointѕList = []
        ctrlPointѕTime = []
        runNum = 1
        previousLegTime = 0
        for tm, run in zip(teamMember, members):
            # probleme avec les boucles ou les variations !
            runRaceLeg = Mopradio.objects.filter(cid=comp_id, id=tm.rid).order_by('rt')
            ctrlPointѕLeg = [ str(rrl.ctrl) for rrl in runRaceLeg ]
            ctrlPointѕTimeLeg = [ formatTime((rrl.rt+previousLegTime)/10) for rrl in runRaceLeg ]
            ctrlPointѕLeg.append("Finish leg "+str(runNum))
            ctrlPointѕTimeLeg.append(formatTime((run.rt+previousLegTime)/10)) # unique utilisation de members
            previousLegTime += run.rt

            ctrlPointѕList.extend(ctrlPointѕLeg) # ce n'est pas le nom du contrôle mais son id
            ctrlPointѕTime.extend(ctrlPointѕTimeLeg) # defaut : ce n'est pas le temps cumulé mais juste le temps dans le leg

            runNum += 1

        ctrlPointsName = [(Mopcontrol.objects.get(cid=comp_id, id=int(ctrl_id)).name).split('-')[0]\
             if (ctrl_id.isnumeric()) else ctrl_id for ctrl_id in ctrlPointѕList ]

        context={"competition": competition,
             "categories": categories,
             "category": selectedCat,
             "runner_name": team.name,
             "runner_club": Moporganization.objects.get(id=team.org, cid=comp_id).name if team.org != 0 else '',
             "runner_status": runnerStatus[team.stat],
             "ctrlPointѕ": zip(ctrlPointsName, ctrlPointѕTime)
        }

    else: # il reste à corriger les mêmes défauts : numéros ou noms des controles, ordre si boucles
        runner = Mopcompetitor.objects.get(cid=comp_id, cls=cls_id, id=run_id)
        club = Moporganization.objects.get(id=runner.org, cid=comp_id).name
        # get control points for a runner
        ctrlPointѕList = [str(c) for c in Mopclasscontrol.objects.\
                        filter(cid=comp_id, id=cls_id).\
                        order_by('ord').values_list("ctrl", flat=True)]
        ctrlPointѕList.append("Finish")

        runRace = Mopradio.objects.filter(cid=comp_id, id=run_id).order_by('rt')
        runTime = {str(key): formatTime(value/10) for key, value
               in zip(runRace.values_list("ctrl", flat=True),
                      runRace.values_list("rt", flat=True))}
        runTime["Finish"]=formatTime(runner.rt/10)
        ctrlPointѕTime = [runTime[key] if key in runTime else "---" for key in ctrlPointѕList]
        context={"competition": competition,
             "categories": categories,
             "category": selectedCat,
             "runner_name": runner.name.replace(','," "),
             "runner_club": club,
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

