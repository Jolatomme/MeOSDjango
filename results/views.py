# Django imports
from django.shortcuts     import render, get_object_or_404
from django.http          import HttpResponse
from django.views.generic import ListView
from django.db.models     import Max
from django.http          import Http404
from django.views.decorators.csrf import csrf_exempt
# Settings
from MeOSDjango.dev_settings import MEOS_PASSWORD

# Other imports
import markdown
import xml.etree.ElementTree as ET
import itertools

# Models imports
from .models          import (Mopcompetition, Mopclass, Mopteammember, Mopteam, Mopcontrol,
                              Mopcompetitor, Mopradio, Mopclasscontrol, Moporganization,
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
    """ renvoi la liste des catégories de la compétition, plus les legs pour les relais """
    competition = getCompetition(comp_id)
    categories = categoriesList(comp_id)
    context = {"competition" : competition,
               "categories": categories}
    return render(request, "category.html", context)

def DisplayCategory(request, comp_id, cls_id):
    """ Display category details """
    competition = getCompetition(comp_id)
    categories = categoriesList(comp_id)
    try:
        category = Mopclass.objects.get(cid=comp_id, id=cls_id)
    except:
        raise Http404("Cette catégorie n'existe pas")

    # nombre de legs pour savoir si c'est un relai
    num_legs = nombreLegs(comp_id)
    # récupérer la valeur de 'leg' dans le GET (si il y en a)
    testGet = request.GET.get("leg")
    if testGet == None:
        legInGet = 0
    else:
        try:
            legInGet = int(testGet)
            if legInGet  < 1 | legInGet > num_legs:
                legInGet = 0
        except:
            legInGet = 0

    # precedent ?
    # suivant ?

    if (num_legs > 1) and (legInGet != 0): # affichage d'un leg en particulier dans le relais
        typeFormat = 'run' # information pour le template
        # query des équipes,
        # query des coureurs de ces équipes sur ce leg,
        # query des résultats de ces coureurs
        qTeam = Mopteam.objects.filter(cid=comp_id, cls=cls_id)
        qRunnerLeg = Mopteammember.objects\
          .filter(cid=comp_id, id__in=qTeam.values_list('id', flat=True), leg=legInGet)\
          .values_list('rid', flat=True)
        qResults = Mopcompetitor.objects.filter(cid=comp_id, id__in=qRunnerLeg, stat__gt=0)\
          .order_by('stat','rt', 'id')
        # pour les résultats spécifiques d'un leg, on affiche le nom de l'équipe
        # en plus du nom du coureur
        # lien : dictR [id du runner] = nom de l'équipe
        dictR = { runner : team for runner, team\
          in zip(qRunnerLeg, qTeam.values_list('name', flat=True))}
        listeComplement = [ dictR[r] for r in qResults.values_list('id', flat=True)]

        # liste des clubs pour chaque ligne
        listeClub = [Moporganization.objects.get(id=org, cid=comp_id).name if org != 0 else ''\
          for org in qResults.values_list("org", flat=True)]

    elif (num_legs > 1) and (legInGet == 0) : # affichage de l'ensemble des legs du relai
        typeFormat = 'team' # information pour le template
        # query des résultats des équipes pour cette catégorie (dans Mopteam)
        qResults = Mopteam.objects.filter(cid=comp_id, cls=cls_id, stat__gt=0)\
          .order_by('stat', 'rt', 'id')
        # pour les résultats globaux du relais, on affiche les noms des membres
        # en plus de celui de l'équipe
        listeComplement = []
        sep = " / "
        for team in qResults:
            listeRid = Mopteammember.objects.filter(cid=comp_id, id=team.id).order_by('leg')\
              .values_list('rid', flat=True)
            listeComplement.append(sep.join([Mopcompetitor.objects.get(cid=comp_id, id=rid).name\
              for rid in listeRid]))

        # liste des clubs pour chaque ligne
        listeClub = [Moporganization.objects.get(id=org, cid=comp_id).name if org != 0 else ''\
          for org in qResults.values_list("org", flat=True)]

    else: # épreuve individuelle
        # query des résultats indivduels
        # liste des clubs pour chaque ligne
        qResults = Mopcompetitor.objects.filter(cls=cls_id, cid=comp_id, stat__gt=0)\
                  .order_by('stat', 'rt', 'id')
        listeClub = [Moporganization.objects.get(id=org, cid=comp_id).name if org != 0 else ''\
            for org in qResults.values_list("org", flat=True)]
        listeComplement = [] # rien pour les épreuves individuelles
        typeFormat = 'run'

    # liste des résultats sans les dixièmes de seconde
    # liste des écarts au premier du classement
    # liste des statuts
    listeTime, listeTimeDiff = [], []
    rBase = qResults[0].rt if len(qResults) > 0 else 0
    for r in qResults:
        if r.stat == 1:
            listeTime.append(formatTime(r.rt/10))
            listeTimeDiff.append(formatTime((r.rt - rBase)/10) if r.rt != rBase else '')
        else:
            listeTime.append(runnerStatus[r.stat])
            listeTimeDiff.append('')

    context = {"competition" : competition,
               "categories": categories,
               "selectedCat": category,
               "leg":legInGet,
               "results": itertools.zip_longest(qResults, listeTime, listeTimeDiff, listeClub, listeComplement),
               "type":typeFormat}
    return render(request, "catDetail.html", context)

def DisplayRunDetails(request, comp_id, cls_id, run_id):
    """ Display control point and time for a runner (not a team) """
    competition = getCompetition(comp_id)
    categories = categoriesList(comp_id)
    try:
        category = Mopclass.objects.get(cid=comp_id, id=cls_id)
    except:
        raise Http404("Cette catégorie n'existe pas")
    try:
        runner = Mopcompetitor.objects.get(cid=comp_id, id=run_id)
    except:
        raise Http404("Cour/eur/euse inconnu/e")

    Club = Moporganization.objects.get(id=runner.org, cid=comp_id).name if runner.org != 0 else ''

    # precedent ?
    # suivant ?

# on vérifie si c'est un leg de relais
    try:
        runLeg = Mopteammember.objects.get(cid=comp_id, rid=run_id)
        forLeg = runLeg.leg
    except:
        forLeg = 1
# get control points for the class of this runner
    ctrlPointѕList = list(Mopclasscontrol.objects.filter(cid=comp_id, id=cls_id, leg=forLeg)\
      .order_by('ord').values_list('ctrl', flat=True))
    ctrlPointsName = [Mopcontrol.objects.get(cid=comp_id, id=ctrl).name for ctrl in ctrlPointѕList]
    ctrlPointsTime = ['---' for cpn in ctrlPointsName] # liste vide
# get radio for the runner
    runRace = Mopradio.objects.filter(cid=comp_id, id=run_id)\
      .order_by('rt')
# rapprocher les controles trouvés avec la liste des controles
    i = 0
    for rr in runRace:
        try:
            i = ctrlPointѕList.index(rr.ctrl, i)
            ctrlPointsTime[i] = formatTime(rr.rt/10)
        except:
            break

    ctrlPointѕList.append("Finish")
    ctrlPointsName.append("Finish")
    ctrlPointsTime.append(formatTime(runner.rt/10))

    context={"competition": competition,
             "categories": categories,
             "category": category,
             "runner_name": runner.name.replace(','," "),
             "runner_club": Club,
             "runner_status": runnerStatus[runner.stat],
             "ctrlPointѕ": zip(ctrlPointsName, ctrlPointsTime)
    }

    return render(request, "circuitDetail.html", context)

def DisplayTeamDetails(request, comp_id, cls_id, team_id):
    """ Display control point and time for a team """
    competition = getCompetition(comp_id)
    categories = categoriesList(comp_id)
    try:
        category = Mopclass.objects.get(cid=comp_id, id=cls_id)
    except:
        raise Http404("Cette catégorie n'existe pas")
    try:
        team = Mopteam.objects.get(cid=comp_id, id=team_id)
    except:
        raise Http404("Équipe inconnue")
    Club = Moporganization.objects.get(id=team.org, cid=comp_id).name if team.org != 0 else ''

    # precedent ?
    # suivant ?

    typeFormat = 'relai'
# get runner list for this team
    teamMembers = Mopteammember.objects.filter(cid=comp_id, id=team_id).order_by('leg')
    members = [Mopcompetitor.objects.get(cid=comp_id, id=tm.rid) for tm in teamMembers]

# control points for all runners in a global list
    ctrlPointѕList = []
    ctrlPointѕTime = []
    runNum = 1
    previousLegTime = 0
    for tm, run in zip(teamMembers, members):
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
         "category": category,
         "runner_name": team.name,
         "runner_club": Club,
         "runner_status": runnerStatus[team.stat],
         "ctrlPointѕ": zip(ctrlPointsName, ctrlPointѕTime)
    }

    return render(request, "circuitDetail.html", context)



def MarkdownView(request, article_id):
    md = markdown.Markdown(extensions=["fenced_code"])
    markdown_content = MeosTutorial.objects.get(pk=article_id)
    markdown_content.content = md.convert(markdown_content.text)
    context = {"markdown_content": markdown_content}
    return render(request, "markdown_content.html",
        context=context)

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


def DisplayCategoryComplet (request, comp_id, cls_id):
    """ Display category details with full details (relay or individual) """
    competition = getCompetition(comp_id)
    categories = categoriesList(comp_id)
    try:
        category = Mopclass.objects.get(cid=comp_id, id=cls_id)
    except:
        raise Http404("Cette catégorie n'existe pas")

    # nombre de legs pour savoir si c'est un relai
    num_legs = nombreLegs(comp_id)
    # récupérer la valeur de 'leg' dans le GET (si il y en a)
    testGet = request.GET.get("leg")
    if testGet == None:
        legInGet = 0
    else:
        try:
            legInGet = int(testGet)
            if legInGet  < 1 | legInGet > num_legs:
                legInGet = 0
        except:
            legInGet = 0

    # precedent ?
    # suivant ?

    if (num_legs > 1) and (legInGet != 0): # affichage d'un leg en particulier dans le relais
        typeFormat = 'run' # information pour le template
        # query des équipes,
        # query des coureurs de ces équipes sur ce leg,
        # query des résultats de ces coureurs
        # liste des clubs pour chaque ligne de résultat
        qTeam = Mopteam.objects.filter(cid=comp_id, cls=cls_id)
        qRunnerLeg = Mopteammember.objects\
          .filter(cid=comp_id, id__in=qTeam.values_list('id', flat=True), leg=legInGet)\
          .values_list('rid', flat=True)
        qResults = Mopcompetitor.objects.filter(cid=comp_id, id__in=qRunnerLeg, stat__gt=0)\
          .order_by('stat','rt', 'id')
        listeClub = [Moporganization.objects.get(id=org, cid=comp_id).name if org != 0 else ''\
          for org in qResults.values_list("org", flat=True)]

        # pour les résultats spécifiques d'un leg, on affiche le nom de l'équipe
        # en plus du nom du coureur
        # lien : dictR [id du runner] = nom de l'équipe
        dictR = { runner : team for runner, team\
          in zip(qRunnerLeg, qTeam.values_list('name', flat=True))}
        listeComplement = [dictR[r] for r in qResults.values_list('id', flat=True)]

        # liste des id des contrôles du circuit pour ce leg
        # liste des noms des contrôles
        # liste template qui va servir pour les temps de passage de chaque coureur
        listCtrlPointѕ = list(Mopclasscontrol.objects.filter(cid=comp_id, id=cls_id, leg=legInGet)\
          .order_by('ord')\
          .values_list('ctrl', flat=True))
        listCtrlPointsName = list([Mopcontrol.objects.get(cid=comp_id, id=ctrl).name for ctrl in listCtrlPointѕ])
        listCtrlPointsTimeTemplate = ['---' for cpn in listCtrlPointѕ]
        listCtrlPointѕ.append("Finish")
        listCtrlPointsName.append("Finish leg "+str(legInGet))

        # get radio for the runner
        listeResultats = []
        for runner in qResults:
            qRadio = Mopradio.objects.filter(cid=comp_id, id=runner.id)\
              .order_by('rt')
            # rapprocher les controles trouvés avec la liste des controles
            listCtrlPointsTime = listCtrlPointsTimeTemplate.copy()
            i = 0
            for rr in qRadio:
                try:
                    i = listCtrlPointѕ.index(rr.ctrl, i)
                    listCtrlPointsTime[i] = formatTime(rr.rt/10)
                except:
                    break
            timeRunner = formatTime(runner.rt/10)
            timeRunner += " ("+runnerStatus[runner.stat]+")" if runnerStatus[runner.stat] != 'OK' else ''
            # si le coureur n'est pas OK on précise son statut
            listCtrlPointsTime.append(timeRunner)

            listeResultats.append(listCtrlPointsTime) # liste de listes de résultats

    elif (num_legs > 1) and (legInGet == 0): # affichage de l'ensemble des legs du relai

        # nombre de legs dans la catégorie affichée
        nbLegsInCls = nombreLegs(comp_id, cls_id)

        typeFormat = 'team' # information pour le template

        # liste de liste des id des contrôles du circuit
        # liste des noms des contrôles correspondant (envoyée au template html)
        # liste de liste des template qui vont servir pour les temps de passage de chaque coureur
        list2DCtrlPointѕ = []
        listCtrlPointsName = []
        list2DTimeTemplate = []
        legindex = 0
        while (legindex < nbLegsInCls):
            qClassControl = Mopclasscontrol.objects\
              .filter(cid=comp_id, id=cls_id, leg=legindex+1)\
              .order_by('ord')
            list2DCtrlPointѕ.append(list(qClassControl.values_list('ctrl', flat=True)))
            listName = list(Mopcontrol.objects.get(cid=comp_id, id=ctrl).name\
              for ctrl in list2DCtrlPointѕ[legindex])
            listCtrlPointsName.extend(listName)
            listCtrlPointsName.append("Finish"+str(legindex+1))
            list2DTimeTemplate.append(['---' for cpn in list2DCtrlPointѕ[legindex]])
            list2DTimeTemplate[legindex].append('---')
            legindex += 1

        # query des équipes de la catégorie
        # liste des clubs pour chaque équipe
        # liste des informations complémentaires par équipe (noms des membres)
        # liste de liste des résultats qui sera envoyée au template html
        qResults = Mopteam.objects.filter(cid=comp_id, cls=cls_id, stat__gt=0)\
          .order_by('stat', 'rt', 'id')
        listeClub = [Moporganization.objects.get(id=org, cid=comp_id).name if org != 0 else ''\
          for org in qResults.values_list("org", flat=True)]
        sep = " / "
        listeComplement = []
        listeResultats = []

        for team in qResults:
            # pour chaque équipe, query des membres de l'équipe
            # listeComplement : pour les résultats globaux du relais, on affiche
            # les noms des membres en plus de celui de l'équipe
            qTeammember = Mopteammember.objects.filter(cid=comp_id, id=team.id).order_by('leg')
            qCompetitor = Mopcompetitor.objects.filter(cid=comp_id, id__in=qTeammember.values_list('rid',flat=True))
            listeComplement.append(sep.join(list(qCompetitor.values_list('name',flat=True))))

            # pour chaque membre, query des temps de passage dans radiocontrol
            liste2DResultats =[]
            legindex = 0
            for mb in qTeammember:
                # pour chaque membre de l'équipe, liste des temps intermédiaires
                qRadio = Mopradio.objects\
                  .filter(cid=comp_id, id=mb.rid)\
                  .order_by('rt')
#                if len(qRadio) == 0:
#                    test = mb.id
#                    trace = int('a') 
                # affecter les controles trouvés dans une copie du template pour ce leg
                # PROBLEME : impossible de gérer les circuits avec variations faute de données exportées par Meos

                listCtrlPointsTime = list2DTimeTemplate[legindex].copy()
                i = 0
                runner = Mopcompetitor.objects.get(cid=comp_id, id=mb.rid)
                for rr in qRadio:
                    try:
                        i = list2DCtrlPointѕ[legindex].index(rr.ctrl, i)
                        listCtrlPointsTime[i] = formatTime((rr.rt + runner.it)/10)
                    except:
                        break
                timeRunner = formatTime((runner.rt + runner.it)/10)
                # si le coureur n'est pas OK on précise son statut
                timeRunner += " ("+runnerStatus[runner.stat]+")" if runnerStatus[runner.stat] != 'OK' else ''
                # pour le dernier coureur, si l'équipe n'est pas OK on précise son statut
                if (legindex + 1) == nbLegsInCls:
                    timeRunner += " team "+runnerStatus[team.stat] if runnerStatus[team.stat] != 'OK' else ''
                listCtrlPointsTime[-1] = timeRunner
                liste2DResultats.extend(listCtrlPointsTime) # liste de listes de résultats
                legindex += 1
            listeResultats.append(liste2DResultats)

    else: # épreuve individuelle
        typeFormat = 'run'
        # query des résultats indivduels
        # liste des clubs pour chaque ligne
        # pas de complement pour les épreuves individuelles
        qResults = Mopcompetitor.objects.filter(cls=cls_id, cid=comp_id, stat__gt=0)\
                  .order_by('stat', 'rt', 'id')
        listeClub = [Moporganization.objects.get(id=org, cid=comp_id).name if org != 0 else ''\
            for org in qResults.values_list("org", flat=True)]
        listeComplement = []

        # liste des id des contrôles du circuit
        # liste des noms des contrôles
        # liste template qui va servir pour les temps de passage de chaque coureur
        listCtrlPointѕ = list(Mopclasscontrol.objects.filter(cid=comp_id, id=cls_id)\
          .order_by('ord')\
          .values_list('ctrl', flat=True))
        listCtrlPointsName = list([Mopcontrol.objects.get(cid=comp_id, id=ctrl).name for ctrl in listCtrlPointѕ])
        listCtrlPointsTimeTemplate = ['---' for cpn in listCtrlPointѕ]
        listCtrlPointѕ.append("Finish")
        listCtrlPointsName.append("Finish")

        # get radio for the runner
        listeResultats = []
        for runner in qResults:
            qRadio = Mopradio.objects.filter(cid=comp_id, id=runner.id)\
              .order_by('rt')
            # rapprocher les controles trouvés avec la liste des controles
            listCtrlPointsTime = listCtrlPointsTimeTemplate.copy()
            i = 0
            for rr in qRadio:
                try:
                    i = listCtrlPointѕ.index(rr.ctrl, i)
                    listCtrlPointsTime[i] = formatTime(rr.rt/10)
                except:
                    break
            listeResultats.append(listCtrlPointsTime) # liste de listes de résultats
            timeRunner = formatTime(runner.rt/10)
            timeRunner += " ("+runnerStatus[runner.stat]+")" if runnerStatus[runner.stat] != 'OK' else ''
            listCtrlPointsTime.append(timeRunner)

# correction de l'affichage des noms des postes
    i = 0
    while i < len(listCtrlPointsName):
        listCtrlPointsName[i] = listCtrlPointsName[i].partition("-")[0]
        i += 1

    context = {"competition" : competition,
               "categories": categories,
               "selectedCat": category,
               "leg":legInGet,
               "ctrlName": listCtrlPointsName,
               "results": itertools.zip_longest(qResults, listeComplement, listeResultats),
               "type":typeFormat}
    return render(request, "catComplet.html", context)



# Functions based views ENDS ***************

