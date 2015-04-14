# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright 2013 Camptocamp
#    Copyright 2009-2013 Akretion,
#    Author: Emmanuel Samyn, Raphaël Valyi, Sébastien Beau,
#            Benoît Guillot, Joel Grand-Guillaume
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from openerp import models, fields, api, exceptions
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT
from openerp.tools.translate import _
import time


class ClaimMakePicking(models.TransientModel):

    _name = 'claim_make_picking.wizard'
    _description = 'Wizard to create pickings from claim lines'
    claim_line_source_location = fields.Many2one(
        comodel_name='stock.location',
        string='Source Location',
        help="Location where the returned products are from.",
        required=True)
    claim_line_dest_location = fields.Many2one(
        comodel_name='stock.location',
        string='Dest. Location',
        help="Location where the system will stock the returned products.",
        required=True)
    claim_line_ids = fields.Many2many(
        comodel_name='claim.line',
        relation='claim_line_picking',
        column1='claim_picking_id',
        column2='claim_line_id',
        string='Claim lines')

    @api.model
    def _get_claim_lines(self):
        # TODO use custom states to show buttons of this wizard or not instead
        # of raise an error
        line_obj = self.env['claim.line']
        if self._context.get('picking_type') == 'outgoing':
            move_field = 'move_out_id'
        else:
            move_field = 'move_in_id'
        good_lines = []
        line_ids = line_obj.search(
            [('claim_id', '=', self._context['active_id'])])
        for line in line_ids:
            if not line[move_field] or line[move_field].state == 'cancel':
                good_lines.append(line.id)
        if not good_lines:
            raise exceptions.Warning(_(
                'A picking has already been created for this claim.'))
        return good_lines

    # Get default source location
    @api.model
    def _get_source_loc(self):
        loc_id = False
        warehouse_obj = self.env['stock.warehouse']
        warehouse_id = self._context.get('warehouse_id')
        if self._context.get('picking_type') == 'outgoing':
            loc_id = warehouse_obj.read(
                warehouse_id,
                ['lot_stock_id'],
            )['lot_stock_id'][0]
        elif self._context.get('partner_id'):
            loc_id = self.env['res.partner'].browse(
                self._context['partner_id']).property_stock_customer
        return loc_id

    @api.model
    def _get_common_dest_location_from_line(self, line_ids):
        """Return the ID of the common location between all lines. If no common
        destination was found, return False"""
        loc_id = False
        line_obj = self.env['claim.line']
        line_location = []
        for line in line_obj.browse(line_ids):
            if line.location_dest_id.id not in line_location:
                line_location.append(line.location_dest_id.id)
        if len(line_location) == 1:
            loc_id = line_location[0]
        return loc_id

    @api.model
    def _get_common_partner_from_line(self, line_ids):
        """Return the ID of the common partner between all lines. If no common
        partner was found, return False"""
        partner_id = False
        line_obj = self.env['claim.line']
        line_partner = []
        for line in line_obj.browse(line_ids):
            if (line.warranty_return_partner
                    and line.warranty_return_partner.id
                    not in line_partner):
                line_partner.append(line.warranty_return_partner.id)
        if len(line_partner) == 1:
            partner_id = line_partner[0]
        return partner_id

    # Get default destination location
    @api.model
    def _get_dest_loc(self):
        """Return the location_id to use as destination.
        If it's an outoing shippment: take the customer stock property
        If it's an incoming shippment take the location_dest_id common to all
        lines, or if different, return None."""
        loc_id = False
        if self._context.get('picking_type') == 'outgoing' and\
                self._context.get('partner_id'):
            loc_id = self.env['res.partner'].read(
                self._context.get('partner_id'),
                ['property_stock_customer'],
            )['property_stock_customer'][0]
        elif self._context.get('picking_type') == 'incoming' and\
                self._context.get('partner_id'):
            # Add the case of return to supplier !
            line_ids = self._get_claim_lines()
            loc_id = self._get_common_dest_location_from_line(
                line_ids)
        return loc_id

    _defaults = {
        'claim_line_source_location': _get_source_loc,
        'claim_line_dest_location': _get_dest_loc,
        'claim_line_ids': _get_claim_lines,
    }

    @api.multi
    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    def action_create_picking(self):
        self.ensure_one()
        picking_obj = self.env['stock.picking']
        view_obj = self.env['ir.ui.view']
        picking_type = self.env['stock.picking.type']
        name = 'RMA picking out'
        if self._context.get('picking_type') == 'out':
            p_type = picking_type.search([('code', '=', 'outgoing')], limit=1)
            write_field = 'move_out_id'
            note = 'RMA picking out'
        else:
            p_type = picking_type.search([('code', '=', 'incoming')], limit=1)
            write_field = 'move_in_id'
            if self._context.get('picking_type'):
                note = 'RMA picking ' + str(self._context.get('picking_type'))
                name = note
        model = 'stock.picking'
        view_id = view_obj.search([('model', '=', model),
                                   ('type', '=', 'form'),
                                   ])[0]
        # wizard = self.browse(cr, uid, ids[0], context=context)
        claim = self.env['crm.claim'].browse(
            self._context['active_id'])
        partner_id = claim.delivery_address_id.id
        line_ids = [x.id for x in self.claim_line_ids]
        # In case of product return, we don't allow one picking for various
        # product if location are different
        # or if partner address is different
        if self._context.get('product_return'):
            common_dest_loc_id = self._get_common_dest_location_from_line(
                line_ids)
            if not common_dest_loc_id:
                raise exceptions.Warning(_(
                    'A product return cannot be created for various '
                    'destination locations, please choose line with a '
                    'same destination location.'))
            self.env['claim.line'].browse(line_ids).auto_set_warranty()
            common_dest_partner_id = self._get_common_partner_from_line(
                line_ids)
            if not common_dest_partner_id:
                raise exceptions.Warning(_(
                    'A product return cannot be created for various '
                    'destination addresses, please choose line with a '
                    'same address.'))
            partner_id = common_dest_partner_id
        picking_id = picking_obj.create(
            {'origin': claim.number,
             'picking_type_id': p_type.id,
             'move_type': 'one',  # direct
             'state': 'draft',
             'date': time.strftime(DEFAULT_SERVER_DATETIME_FORMAT),
             'partner_id': partner_id,
             'invoice_state': "none",
             'company_id': claim.company_id.id,
             'location_id': self.claim_line_source_location.id,
             'location_dest_id': self.claim_line_dest_location.id,
             'note': note,
             'claim_id': claim.id,
             }
        )
        # Create picking lines
        fmt = DEFAULT_SERVER_DATETIME_FORMAT
        for wizard_claim_line in self.claim_line_ids:
            move_obj = self.env['stock.move']
            move_id = move_obj.create(
                {'name': wizard_claim_line.product_id.name_template,
                 'priority': '0',
                 'date': time.strftime(fmt),
                 'date_expected': time.strftime(fmt),
                 'product_id': wizard_claim_line.product_id.id,
                 'product_uom_qty':
                    wizard_claim_line.product_returned_quantity,
                 'product_uom': wizard_claim_line.product_id.uom_id.id,
                 'partner_id': partner_id,
                 # 'prodlot_id': wizard_claim_line.prodlot_id.id,
                 'picking_id': picking_id.id,
                 'state': 'draft',
                 'price_unit': wizard_claim_line.unit_sale_price,
                 'company_id': claim.company_id.id,
                 'location_id': self.claim_line_source_location.id,
                 'location_dest_id': self.claim_line_dest_location.id,
                 'note': note,
                 })
        wizard_claim_line.write({write_field: move_id.id})
        if picking_id:
            picking_id.action_confirm()
            picking_id.action_assign()
        domain = ("[('picking_type_id', '=', '%s'), ('partner_id', '=', %s)]" %
                  (p_type.id, partner_id))
        return {
            'name': '%s' % name,
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': view_id.id,
            'domain': domain,
            'res_model': model,
            'res_id': picking_id.id,
            'type': 'ir.actions.act_window',
        }

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
