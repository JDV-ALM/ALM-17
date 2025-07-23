from odoo import models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    # Este modelo solo existe para que otros módulos Almus
    # puedan heredarlo y agregar sus configuraciones