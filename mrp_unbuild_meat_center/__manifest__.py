# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Developer: Almus Dev (JDV-ALM) - www.almus.dev

{
    'name': 'Almus MRP Unbuild Center',
    'version': '17.0.1.1.0',
    'category': 'Manufacturing',
    'summary': 'Extensión de desmantelamiento para centros de desposte con factor de valor',
    'description': """
MRP Unbuild Extension for Meat Processing Centers
=================================================

Este módulo extiende la funcionalidad de desmantelamiento de Odoo para adaptarse
a las necesidades específicas de centros de desposte y procesamiento de carne.

Características principales:
---------------------------
* Estado intermedio 'Ready' para ajustar cantidades antes de confirmar
* Posibilidad de marcar productos como desecho (sin costo)
* Factor de valor por corte para distribución realista de costos
* Distribución automática de costos basada en valor real del corte
* Opción de ajuste manual de distribución de costos
* Validaciones mejoradas y advertencias en tiempo real
* Registro detallado de cantidades esperadas vs reales
* Compatible con trazabilidad por lotes

Nuevas funcionalidades v1.1.0:
-----------------------------
* Factor de valor en subproductos de BoM
* Cálculo inteligente de costos según valor del corte
* Validación de ubicación de desecho al marcar productos
* Advertencia cuando suma de productos excede cantidad inicial
* Soporte para distribución manual de costos
* Validación de método de costeo (no compatible con Standard)

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