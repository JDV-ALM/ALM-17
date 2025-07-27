# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Developer: Almus Dev (JDV-ALM) - www.almus.dev

{
    'name': 'Almus MRP Unbuild Center',
    'version': '17.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Extensión de desmantelamiento para centros de desposte',
    'description': """
MRP Unbuild Extension for Meat Processing Centers
=================================================

Este módulo extiende la funcionalidad de desmantelamiento de Odoo para adaptarse
a las necesidades específicas de centros de desposte y procesamiento de carne.

Características principales:
---------------------------
* Estado intermedio 'Ready' para ajustar cantidades antes de confirmar
* Posibilidad de marcar productos como desecho (sin costo)
* Distribución automática de costos solo entre productos buenos
* Registro detallado de cantidades esperadas vs reales
* Compatible con trazabilidad por lotes

Flujo de trabajo:
----------------
1. Crear orden de desmantelamiento
2. Estado 'Ready': Ajustar cantidades reales y marcar desechos
3. Confirmar: Procesar movimientos y distribuir costos

Desarrollado por Almus Dev (JDV-ALM)
    """,
    'author': 'Almus Dev',
    'website': 'https://www.almus.dev',
    'depends': ['mrp', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/mrp_unbuild_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}