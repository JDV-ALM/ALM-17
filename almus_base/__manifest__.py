{
    "name": "Almus Base",
    "summary": """
        Panel de control para aplicaciones Almus Dev
    """,
    "description": """
        Módulo base que proporciona:
        - Panel informativo de aplicaciones Almus instaladas
        - Espacio en configuración para que otras apps Almus agreguen sus ajustes
        - Estadísticas básicas del ecosistema Almus
    """,
    "license": "LGPL-3",
    "author": "Almus Dev",
    "website": "https://www.almus.dev",
    "category": "Technical",
    "version": "17.0.1.0.0",
    "depends": ["base"],
    "installable": True,
    "auto_install": False,
    "application": False,
    "data": [
        "views/res_config_settings_views.xml",
    ],
}