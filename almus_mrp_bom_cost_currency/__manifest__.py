# -*- coding: utf-8 -*-
{
    'name': 'Manufacturing Cost in Alternative Currency',
    'version': '17.0.1.0.0',
    'category': 'Manufacturing/Manufacturing',
    'summary': 'Calculate manufacturing cost in alternative currency based on BOM components',
    'description': """
        This module calculates manufacturing cost in alternative currency for products 
        based on their Bill of Materials (BOM) components.
        
        Features:
        - Automatic calculation of manufacturing cost in alternative currency
        - Recursive calculation for nested BOMs
        - Integration with existing alternative cost module
        - Use manufacturing alternative cost in pricelists
        - Simple and efficient KISS approach
        
        Dependencies:
        - Requires almus_product_cost_currency module
        - Works with standard MRP module
    """,
    'author': 'Almus Dev (JDV-ALM)',
    'website': 'https://www.almus.dev',
    'license': 'LGPL-3',
    'depends': [
        'mrp',
        'almus_product_cost_currency',
    ],
    'data': [
        'views/product_views.xml',
        'views/product_pricelist_item_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}