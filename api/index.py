"""Point d'entrée Vercel : l'appli Flask, servie comme une fonction Python.

Les fichiers statiques (styles, police, moteur de lecture des tickets) ne passent pas par ici :
ils sont dans public/static, servi directement par Vercel.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from budget import create_app  # noqa: E402

app = create_app()
