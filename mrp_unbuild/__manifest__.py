# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Manufacturing Unbuild Extension',
    'version': '17.0.1.0.0',
    'category': 'Manufacturing/Manufacturing',
    'sequence': 50,
    'summary': 'Unbuild/Disassembly functionality integrated in MRP',
    'description': """
Manufacturing Unbuild Extension
===============================

This module extends the standard MRP module to add unbuild/disassembly functionality.

Key Features:
-------------
* Create Unbuild BOMs to define how to disassemble products
* Process Unbuild Orders using the same interface as Manufacturing Orders
* Track actual yields vs expected yields
* Distribute costs among output products
* Full integration with inventory and accounting

The module is fully integrated into the existing MRP module, providing a seamless
experience for users who need both manufacturing and unbuild capabilities.
    """,
    'author': 'Almus Dev (JDV-ALM)',
    'website': 'https://www.almus.dev',
    'depends': [
        'mrp',
        'mrp_account',
        'stock_account',
    ],
    'data': [
        # Security
        'security/mrp_unbuild_security.xml',
        'security/ir.model.access.csv',
        
        # Data
        'data/mrp_unbuild_data.xml',
        
        # Views
        'views/mrp_unbuild_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'assets': {
        'web.assets_backend': [
            # Los assets se agregarán cuando se desarrollen widgets específicos
        ],
    },
    'images': [
        'static/description/icon.png',
        'static/description/unbuild_screenshot.png',
    ],
    'external_dependencies': {
        'python': [],
        'bin': [],
    },
    'qweb': [],
    'post_init_hook': 'post_init_hook',
}