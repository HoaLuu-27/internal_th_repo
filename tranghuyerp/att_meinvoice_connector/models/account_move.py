import uuid
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'




    # MeInvoice State
    meinvoice_state = fields.Selection([
        ('not_sent', 'Chưa gửi'),
        ('pending', 'Đang xử lý'),
        ('draft_sent', 'Đã tạo nháp'),
        ('published', 'Đã phát hành'),
        ('error', 'Lỗi'),
    ], string='Trạng thái MeInvoice',
        default='not_sent', copy=False,
        index=True, tracking=True,
    )
    #  MeInvoice data
    meinvoice_ref_id = fields.Char(
        'RefID', copy=False, readonly=True, index=True,
        help='GUID tự sinh khi gửi MeInvoice.',
    )
    meinvoice_inv_no = fields.Char(
        'Số HĐ điện tử', copy=False, readonly=True,
        help='Số hóa đơn chính thức do MeInvoice cấp sau khi phát hành.',
    )
    meinvoice_transaction_id = fields.Char(
        'Mã tra cứu', copy=False, readonly=True,
        help='Mã tra cứu hóa đơn chính thức do MeInvoice cấp sau khi phát hành.',
    )
    meinvoice_inv_date = fields.Date(
        'Ngày phát hành HĐ điện tử', copy=False, readonly=True,
    )
    meinvoice_error_msg = fields.Text(
        'Lỗi MeInvoice', copy=False, readonly=True,
    )
    meinvoice_invoice_id = fields.Many2one(
        'meinvoice.invoice',
        string='MeInvoice Invoice Record',
        copy=False, readonly=True,
        help='Record meinvoice.invoice tương ứng.',
    )
    # Computed
    meinvoice_can_send = fields.Boolean(
        compute='_compute_meinvoice_can_send',
        help='True khi posted, out_invoice, chưa gửi hoặc lỗi.',
    )


    @api.depends('state', 'meinvoice_state', 'move_type')
    def _compute_meinvoice_can_send(self):
        for move in self:
            move.meinvoice_can_send = (
                move.state == 'posted'
                and move.move_type == 'out_invoice'
                and move.meinvoice_state in ('not_sent', 'error')
            )
    #  Validate
    def _validate_before_send(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Hóa đơn chưa có khách hàng.'))
        if not self.partner_id.name:
            raise UserError(_('Khách hàng chưa có tên.'))
        lines = self.invoice_line_ids.filtered(lambda l: l.product_id)
        if not lines:
            raise UserError(_('Hóa đơn phải có ít nhất 1 dòng sản phẩm.'))


    # Actions
    def action_meinvoice_insert(self):
        """
        Chiều A: Tạo HĐ nháp trên MeInvoice từ account.move.
        Flow:
            1. Validate
            2. build_from_move() → tạo meinvoice.invoice record + invoice_data
            3. commit → đảm bảo record được lưu dù API fail
            4. api.insert_invoice() → gửi lên MeInvoice
            5. Cập nhật state
        """
        self.ensure_one()
        if not self.meinvoice_can_send:
            raise UserError(_(
                'Hóa đơn phải ở trạng thái Đã xác nhận và chưa được gửi.'
            ))
        self._validate_before_send()

        config = self.env['meinvoice.config'].get_active_config()
        api = self.env['meinvoice.api']

        self.write({
            'meinvoice_state': 'pending',
            'meinvoice_error_msg': False,
        })

        # Step 1: Tạo meinvoice.invoice record trước
        mei, invoice_data = self.env['meinvoice.invoice'].build_from_move(
            self, config
        )
        self.write({'meinvoice_invoice_id': mei.id})
        self.env.cr.commit()  # ← lưu record trước khi gọi API

        # Step 2: Gọi API
        try:
            api.insert_invoice(config, invoice_data, move_id=self.id)
            self.write({'meinvoice_state': 'draft_sent'})
            self.message_post(body=_(
                'HĐ nháp đã tạo trên MeInvoice.<br/>'
                'RefID: <b>%s</b><br/>'
                'Lên portal MeInvoice để ký và phát hành.'
            ) % self.meinvoice_ref_id)
            self.env.cr.commit()

        except Exception as e:
            self.write({
                'meinvoice_state': 'error',
                'meinvoice_error_msg': str(e),
            })
            self.message_post(
                body=_('Tạo HĐ nháp MeInvoice thất bại: %s') % str(e)
            )
            self.env.cr.commit()
            raise

    def action_meinvoice_preview(self):
        """
        Xem HĐ MeInvoice.
        - Chưa phát hành: GET /webapp/viewrefid → bản nháp
        - Đã phát hành:   dùng viewrefid cũng được vì MeInvoice tự trả bản mới nhất
        """
        self.ensure_one()
        if not self.meinvoice_ref_id:
            raise UserError(_('Chưa có RefID. Tạo HĐ nháp trước.'))

        config = self.env['meinvoice.config'].get_active_config()
        api = self.env['meinvoice.api']

        base64_pdf = api.view_by_refid(
            config, ref_id=self.meinvoice_ref_id, move_id=self.id,
        )

        # Tên file theo trạng thái
        if self.meinvoice_state == 'published' and self.meinvoice_inv_no:
            filename = f'HĐ_MeInvoice_{self.meinvoice_inv_no}.pdf'
        else:
            filename = f'Preview_MeInvoice_{self.name}.pdf'

        # Xóa attachment cũ
        self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.id),
            ('name', 'ilike', 'meinvoice'),
        ]).unlink()

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64_pdf,
            'res_model': 'account.move',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=false',
            'target': 'new',
        }

    def action_meinvoice_delete_draft(self):
        """Xóa HĐ nháp chưa phát hành trên MeInvoice."""
        self.ensure_one()
        if self.meinvoice_state != 'draft_sent':
            raise UserError(_('Chỉ xóa được HĐ ở trạng thái Đã tạo nháp.'))

        config = self.env['meinvoice.config'].get_active_config()
        api = self.env['meinvoice.api']
        api.delete_invoice(
            config, ref_id=self.meinvoice_ref_id, move_id=self.id,
        )
        self.write({
            'meinvoice_state': 'not_sent',
            'meinvoice_ref_id': False,
            'meinvoice_error_msg': False,
            'meinvoice_invoice_id': False,
        })
        self.message_post(body=_('Đã xóa HĐ nháp trên MeInvoice.'))

    def action_meinvoice_refresh_status(self):
        """
        Cập nhật trạng thái HĐ từ MeInvoice.
        Dùng khi cần check HĐ đã được ký + phát hành chưa.
        """
        self.ensure_one()
        if not self.meinvoice_ref_id:
            raise UserError(_('Hóa đơn chưa có RefID.'))

        config = self.env['meinvoice.config'].get_active_config()
        api = self.env['meinvoice.api']

        results = api.get_invoice_list(
            config, ref_ids=[self.meinvoice_ref_id]
        )

        if not results:
            raise UserError(_('Không tìm thấy HĐ trên MeInvoice.'))
        result = results[0]
        inv_no = result.get('InvNo', '')
        is_published = inv_no and inv_no != '<Chưa cấp số>'
        vals = {}
        if is_published:
            vals['meinvoice_state'] = 'published'
            vals['meinvoice_inv_no'] = inv_no
            inv_date = result.get('InvDate', '')
            if inv_date and len(inv_date) >= 10:
                vals['meinvoice_inv_date'] = inv_date[:10]
        self.write(vals)
        # Sync sang meinvoice.invoice record
        if self.meinvoice_invoice_id and is_published:
            self.meinvoice_invoice_id.write({
                'inv_no': inv_no,
                'state': 'published',
            })
        self.message_post(body=_(
            'Đã cập nhật trạng thái MeInvoice.<br/>'
            'Số HĐ: <b>%s</b>'
        ) % (inv_no or 'Chưa cấp số'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã cập nhật'),
                'message': _('Trạng thái MeInvoice đã được cập nhật.'),
                'type': 'success',
            },
        }