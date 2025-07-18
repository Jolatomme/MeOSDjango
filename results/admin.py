from django.contrib import admin
from .models        import (Mopclass, Mopclasscontrol, Mopcompetition,
                            Mopcompetitor, Mopcontrol, Moporganization,
                            Mopradio, Mopteam, Mopteammember, MeosTutorial)

admin.site.register(Mopclass)
admin.site.register(Mopclasscontrol)
admin.site.register(Mopcompetition)
admin.site.register(Mopcompetitor)
admin.site.register(Mopcontrol)
admin.site.register(Moporganization)
admin.site.register(Mopradio)
admin.site.register(Mopteam)
admin.site.register(Mopteammember)
admin.site.register(MeosTutorial)
