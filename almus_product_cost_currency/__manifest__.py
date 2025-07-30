# -*- coding: utf-8 -*-
{
    'name': 'Product Cost in Alternative Currency',
    'version': '17.0.1.2.0',
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
        - Batch processing for large databases
        - Error handling and logging
        - Recalculation button in settings
        
        Performance optimizations:
        - Batch updates for currency changes
        - SQL optimization for large datasets
        - Proper error handling and recovery
    """,
    'author': 'Almus Dev (JDV-ALM)',
    'website': 'https://www.almus.dev',
    'license': 'LGPL-3',
    'depends': [
        'product',
        'base_setup',
        'stock',
        'almus_base',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/cost_recalculation_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/product_views.xml',
        'views/product_pricelist_item_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}