# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Developer: Almus Dev (JDV-ALM) - www.almus.dev

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MrpBomByproduct(models.Model):
    """Extensión de subproductos de BoM para incluir factor de valor"""
    _inherit = 'mrp.bom.byproduct'
    
    value_factor = fields.Float(
        string='Factor de Valor',
        default=1.0,
        digits=(12, 2),
        help="Factor multiplicador para distribución de costos. "
             "Ej: 1.0 = valor estándar, 10.0 = 10 veces más valioso, "
             "0.5 = mitad del valor estándar"
    )
    
    @api.constrains('value_factor')
    def _check_value_factor(self):
        """Valida que el factor de valor sea positivo"""
        for record in self:
            if record.value_factor <= 0:
                raise ValidationError(_(
                    'El factor de valor debe ser mayor que cero. '
                    'Use 1.0 para valor estándar.'
                ))