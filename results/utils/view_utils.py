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
