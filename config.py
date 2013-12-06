# use only valid hostnames
PROXYMAPS = {
    3128 : ("ya.ru", 80),
    5000 : ("192.168.206.115", 5000),
    31337 : ("punk.psviderski.name", 22),
    6000 : ("192.168.206.115", 6000),
}

SESSIONS_DIR = "/srv/sessions"

FILTER_WINDOW_SIZE = 1024

FILTER_RE = [
    r'(\b\w{31}=.*?){2}'
]
