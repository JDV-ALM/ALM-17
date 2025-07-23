# -*- coding: utf-8 -*-
{
    'name': 'Product Cost in Alternative Currency',
    'version': '17.0.1.1.0',
    'category': 'Inventory/Inventory',
    'summary': 'Display product cost in alternative currency and use it in pricelists',
    'description': """
        This module adds a field to display product cost in an alternative currency.
        The cost is automatically recalculated when the standard cost changes.
        
        Features:
        - Configurable alternative currency in settings
        - Automatic conversion when standard cost updates
        - Display in product form after standard price
        - Use alternative cost as base for pricelist calculations
        - New pricelist rule option: "Alternative Cost"
    """,
    'author': 'Almus Dev (JDV-ALM)',
    'website': 'https://www.almus.dev',
    'license': 'LGPL-3',
    'depends': [
        'product',
        'base_setup',
        'almus_base',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/product_views.xml',
        'views/product_pricelist_item_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}