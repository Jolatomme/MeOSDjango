from django.views.generic import ListView
from .models  import MeosTutorial

class TutoView(ListView):
    template_name = "results/tuto.html"

    def get_queryset(self):
        """ Return the tutorials """
        return MeosTutorial.objects.all()
