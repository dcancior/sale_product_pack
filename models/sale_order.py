# Copyright 2019 Tecnativa - Ernesto Tejeda
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import _, api, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def copy(self, default=None):
        sale_copy = super().copy(default)
        # desvinculamos las líneas de paquete que no deberían ser copiadas
        pack_copied_lines = sale_copy.order_line.filtered(
            lambda l: l.pack_parent_line_id.order_id == self
        )
        pack_copied_lines.unlink()
        return sale_copy

    @api.onchange("order_line")
    def check_pack_line_unlink(self):
        """Al menos en la vista editable de árbol embebido, Odoo devuelve un recordset en
        _origin.order_line solo cuando las líneas son desvinculadas y esto es exactamente
        lo que necesitamos
        """
        # Evitar recursión infinita
        if self.env.context.get('skip_pack_onchange'):
            return
            
        origin_line_ids = self._origin.order_line.ids
        line_ids = self.order_line.ids
        removed_line_ids = list(set(origin_line_ids) - set(line_ids))
        removed_line = self.env["sale.order.line"].browse(removed_line_ids)
        
        # Validación original para líneas de paquete no modificables
        if removed_line.filtered(
            lambda x: x.pack_parent_line_id
            and not x.pack_parent_line_id.product_id.pack_modifiable
        ):
            raise UserError(
                _(
                    "No puedes eliminar esta línea porque es parte de un paquete en "
                    "esta orden de venta. Para eliminar esta línea necesitas "
                    "eliminar el paquete completo"
                )
            )
        
        # 🆕 AUTO-GUARDADO: Cuando se elimina un paquete padre, auto-guardar para eliminar líneas hijo
        pack_parent_lines_removed = removed_line.filtered(
            lambda line: line.product_id.pack_ok and line.pack_child_line_ids
        )
        
        if pack_parent_lines_removed and self.id:
            # Crear comandos de eliminación para las líneas padre del paquete
            vals = {
                'order_line': [(2, line.id, False) for line in pack_parent_lines_removed]
            }
            
            # Ejecutar write con contexto especial para evitar recursión
            self.with_context(skip_pack_onchange=True).write(vals)
            
            # Recargar el recordset para reflejar los cambios
            self.invalidate_cache()
            
            # Retornar acción para recargar la vista
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

    def write(self, vals):
        if "order_line" in vals:
            to_delete_ids = [e[1] for e in vals["order_line"] if e[0] == 2]
            
            # 🆕 NUEVA FUNCIONALIDAD: Buscar líneas padre de paquetes que se van a eliminar
            pack_parent_lines_to_delete = self.env["sale.order.line"].browse(to_delete_ids).filtered(
                lambda line: line.product_id.pack_ok and line.pack_child_line_ids
            )
            
            # 🆕 Obtener todos los IDs de líneas hijo que deben eliminarse cuando se elimina el paquete padre
            pack_children_to_delete_ids = []
            for pack_parent in pack_parent_lines_to_delete:
                pack_children_to_delete_ids.extend(pack_parent.pack_child_line_ids.ids)
            
            # Buscar sub-paquetes existentes que deben eliminarse (funcionalidad original)
            subpacks_to_delete_ids = (
                self.env["sale.order.line"]
                .search(
                    [("id", "child_of", to_delete_ids), ("id", "not in", to_delete_ids)]
                )
                .ids
            )
            
            # 🆕 Combinar las líneas hijo del paquete con los sub-paquetes
            all_children_to_delete = list(set(subpacks_to_delete_ids + pack_children_to_delete_ids))
            
            # Procesar comandos existentes y agregar comandos de eliminación para las líneas hijo
            if all_children_to_delete:
                for cmd in vals["order_line"]:
                    if cmd[1] in all_children_to_delete:
                        if cmd[0] != 2:
                            cmd[0] = 2
                        all_children_to_delete.remove(cmd[1])
                
                # Agregar comandos de eliminación para las líneas hijo restantes
                for to_delete_id in all_children_to_delete:
                    vals["order_line"].append([2, to_delete_id, False])
                    
        return super().write(vals)

    def _get_update_prices_lines(self):
        res = super()._get_update_prices_lines()
        result = self.order_line.browse()
        index = 0
        while index < len(res):
            line = res[index]
            result |= line
            index += 1
            if line.product_id.pack_ok and line.pack_type == "detailed":
                index += len(line.product_id.pack_line_ids)
        return result