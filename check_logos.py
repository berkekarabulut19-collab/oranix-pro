import requests, json

leagues = ['tur.1','esp.1','eng.1','ger.1','ita.1','fra.1','uefa.champions_league']
for lg in leagues:
    try:
        r = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard', timeout=5)
        d = r.json()
        evs = d.get('events',[])
        for e in evs[:2]:
            comp = e.get('competitions',[{}])[0]
            teams = comp.get('competitors',[])
            for t in teams[:2]:
                td = t.get('team',{})
                name = td.get('displayName','')
                logo = td.get('logo','')
                tid = td.get('id','')
                print(f"LEAGUE={lg} | TEAM={name} | ID={tid} | LOGO={logo}")
    except Exception as ex:
        print(f'{lg}: ERROR {ex}')
