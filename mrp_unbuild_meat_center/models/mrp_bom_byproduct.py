# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Developer: Almus Dev (JDV-ALM) - www.almus.dev

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MrpBomByproduct(models.Model):
    """Extensión de subproductos de BoM para incluir factor de valor y exclusión de costos"""
    _inherit = 'mrp.bom.byproduct'
    
    value_factor = fields.Float(
        string='Factor de Valor',
        default=1.0,
        digits=(12, 2),
        help="Factor multiplicador para distribución de costos.\n"
             "Rango permitido: 0.01 a 100.00\n"
             "• 100.00 = Producto premium (máximo valor)\n"
             "• 1.00 = Producto estándar (valor base)\n"
             "• 0.01 = Producto de mínimo valor"
    )
    
    no_cost_distribution = fields.Boolean(
        string='No Distribuir Costos',
        default=False,
        help="Si está marcado, este producto no recibirá costos del desmantelamiento.\n"
             "Útil para subproductos de valor mínimo o residuos con algún valor."
    )
    
    @api.constrains('value_factor')
    def _check_value_factor(self):
        """Valida que el factor de valor esté en rango permitido"""
        for record in self:
            if not record.no_cost_distribution:
                if record.value_factor < 0.01 or record.value_factor > 100:
                    raise ValidationError(_(
                        'El factor de valor debe estar entre 0.01 y 100.00\n'
                        'Valor actual: %.2f\n\n'
                        'Referencia:\n'
                        '• 100.00 = 100 veces más valioso que el estándar\n'
                        '• 1.00 = Valor estándar\n'
                        '• 0.01 = 100 veces menos valioso que el estándar\n\n'
                        'Si el producto no debe recibir costos, marque "No Distribuir Costos"'
                    ) % record.value_factor)
    
    @api.onchange('no_cost_distribution')
    def _onchange_no_cost_distribution(self):
        """Ajusta el factor de valor cuando se marca/desmarca no distribuir costos"""
        if self.no_cost_distribution:
            self.value_factor = 0.0
        elif self.value_factor == 0.0:
            self.value_factor = 1.0