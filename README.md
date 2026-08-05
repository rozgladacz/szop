# OPOS — kalkulator kosztów oddziałów

OPOS to serwerowa aplikacja FastAPI do budowania rozpisek, przechowywania prywatnej biblioteki szablonów oddziałów i eksportu eleganckich kart do HTML/PDF.

## Najważniejsze założenia

- Oddział powstaje bezpośrednio w rozpisce albo jako niezależna kopia szablonu z Armii.
- Wpis rozpiski może reprezentować kilka identycznych oddziałów o wspólnym profilu.
- Koszt jednego oddziału jest liczony przez wersjonowany ruleset YAML i zaokrąglany half-up przed pomnożeniem przez liczbę kopii.
- Karty pokazują wspólny profil i koszt jednego oddziału, bez liczebności modeli i liczby kopii.
- OPOS nie zawiera Zbrojowni, dziedziczenia, stanu bitewnego, zaklęć, kart strategicznych ani eksportu XLSX.

## Uruchomienie lokalne

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Aplikacja będzie dostępna pod `http://127.0.0.1:8000`. Pierwszy start tworzy świeżą bazę `data/opos.db`, konto `admin` oraz losowe hasło zapisane w `data/.initial_admin_password`.

## Reguły i testy

- Normatywne zasady: `app/static/docs/OPOS.docx`.
- Publikowany odpowiednik: `app/static/docs/OPOS.pdf`.
- Jedyny wykonywalny ruleset: `app/rulesets/opos/v1/rules.yaml`.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\opos_rules_check.py
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

Na systemie z `make`: `make check`.

## Wdrożenie

Kontenery aplikacji i backupu korzystają ze wspólnego katalogu `data/`. Instrukcja: [DEPLOY.md](DEPLOY.md). Przyszły kanał wydań to `rozgladacz/opos`; utworzenie repozytorium i zmiana `origin` nie są częścią tego cut-overu.

Więcej informacji: [docs/README.md](docs/README.md).
