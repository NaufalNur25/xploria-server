"""Native, per-program Hospital APIs for Blockly and IoT Lab canvas widgets."""
import copy
import math
import threading
import queue
import time
import uuid


class HospitalWidgetSession:
    def __init__(self, project_id, session_id, data, send, sleep, sources, hal=None):
        self.project_id, self.session_id = project_id, session_id
        self.DATA_IOTLAB = data
        self.data_version = 0
        self._send, self._sleep = send, sleep
        self.sources = sources
        self.active = True
        self.events, self.results = queue.Queue(), {}
        self.handlers, self.forms = {}, {}
        self.context = None
        self.seen = set()
        self.received = set()
        self.pending = set()
        self._lock = threading.Lock()
        self._hal = hal
        self.ready = False
        self._closed = False

    def __getattr__(self, name):
        # Preserve existing HospitalHAL APIs, including Jitsi.
        if self._hal is not None:
            return getattr(self._hal, name)
        raise AttributeError(name)

    def accept_event(self, event):
        if not self.active or not self.ready:
            raise ValueError("Program belum siap atau sudah berhenti.")
        self.validate_event(event)
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("event_id diperlukan.")
        if event_id in self.received:
            return "duplicate"
        self.received.add(event_id)
        self.events.put(copy.deepcopy(event))
        return "accepted"

    def validate_event(self, event):
        uid, topic = event.get("source_uid"), event.get("topic")
        if uid not in self.sources or topic not in ("form", "scan", "button"):
            raise ValueError("Blok sumber tidak aktif atau topik tidak dikenal.")
        key = (topic, uid)
        if topic == "form":
            form = self.forms.get(uid)
            if form is None:
                raise ValueError("Blok pembuatan formulir belum dijalankan.")
            key = (topic, form["name"])
            answers = event.get("answers")
            if not isinstance(answers, dict):
                raise ValueError("Jawaban formulir harus berupa objek.")
            labels = {f["label"] for f in form["fields"]}
            if set(answers) != labels:
                raise ValueError("Jawaban harus sesuai pertanyaan formulir.")
            for field in form["fields"]:
                value = answers[field["label"]]
                if field["type"] == "number":
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise ValueError("Jawaban angka harus finite.")
                elif not isinstance(value, str) or not value.strip():
                    raise ValueError("Semua pertanyaan wajib diisi.")
                elif field["type"] == "choice" and value not in field["options"]:
                    raise ValueError("Jawaban pilihan tidak tersedia.")
        if key not in self.handlers:
            raise ValueError("Belum ada blok kejadian yang sesuai untuk widget ini.")
        version = event.get("snapshot_version", self.data_version)
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise ValueError("Versi snapshot tidak valid.")
        if "snapshot" in event and not isinstance(event["snapshot"], dict):
            raise ValueError("Snapshot harus berupa objek.")

    def accept_result(self, request_id, result):
        with self._lock:
            if not self.active or request_id not in self.pending:
                raise ValueError("Permintaan penyimpanan tidak aktif.")
            version = result.get("snapshot_version", self.data_version)
            if not isinstance(result.get("ok"), bool) or isinstance(version, bool) or not isinstance(version, int) or version < 0:
                raise ValueError("Hasil penyimpanan tidak valid.")
            if "snapshot" in result and not isinstance(result["snapshot"], dict):
                raise ValueError("Snapshot harus berupa objek.")
            if request_id not in self.results:
                self.results[request_id] = copy.deepcopy(result)

    def stop(self):
        self.active = False
        self.ready = False


    def emit(self, kind, **payload):
        self._send(action="hospital_widget", kind=kind, project_id=self.project_id,
                   session_id=self.session_id, **payload)

    def report(self, uid, channel, value):
        self.emit("value", block_uid=uid, channel=channel, value=value)
        return value

    def on_scan(self, uid, callback):
        self.handlers[("scan", uid)] = callback
        self.emit("binding", block_uid=uid, topic="scan")

    def on_button(self, uid, callback):
        self.handlers[("button", uid)] = callback
        self.emit("binding", block_uid=uid, topic="button")

    def on_form(self, uid, name, callback):
        key = ("form", name)
        if key in self.handlers:
            raise ValueError("Nama formulir pada kejadian kirim harus unik: " + name)
        self.handlers[key] = callback
        self.emit("binding", block_uid=uid, topic="form", name=name)

    def form(self, uid, name, fields):
        if uid not in self.sources or not isinstance(name, str) or not name.strip():
            raise ValueError("Identitas blok dan nama formulir diperlukan.")
        if not isinstance(fields, list) or not fields:
            raise ValueError("Tambahkan setidaknya satu pertanyaan.")
        fields = copy.deepcopy(fields)
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get("label"), str) or not field["label"].strip():
                raise ValueError("Label pertanyaan diperlukan.")
            if field.get("type") not in ("text", "number", "choice"):
                raise ValueError("Tipe pertanyaan tidak didukung.")
            if field["type"] == "choice":
                options = field.get("options")
                if not isinstance(options, list) or not options or any(not isinstance(o, str) or not o.strip() for o in options) or len(set(options)) != len(options):
                    raise ValueError("Pilihan harus terisi dan unik.")
        labels = [f["label"] for f in fields]
        if len(labels) != len(set(labels)):
            raise ValueError("Setiap pertanyaan dalam formulir harus memiliki label berbeda.")
        if any(f["name"] == name and key != uid for key, f in self.forms.items()):
            raise ValueError("Gunakan nama berbeda untuk setiap formulir: " + name)
        self.forms[uid] = {"name": name, "fields": fields}
        self.emit("form", block_uid=uid, name=name, fields=fields)

    def dispatch(self, event):
        uid, topic = event.get("source_uid"), event.get("topic")
        if not self.active or uid not in self.sources:
            return
        event_id = event.get("event_id")
        if not event_id or event_id in self.seen:
            return
        # Events are never replayed in a session, including a failed handler.
        self.seen.add(event_id)
        key = (topic, uid)
        if topic == "form":
            form = self.forms.get(uid)
            if form is None:
                raise ValueError("Blok pembuatan formulir belum dijalankan.")
            key = (topic, form["name"])
        handler = self.handlers.get(key)
        if handler is None:
            raise ValueError("Belum ada blok kejadian yang sesuai untuk widget ini.")
        self.validate_event(event)
        version = event.get("snapshot_version", self.data_version)
        if version >= self.data_version:
            self.DATA_IOTLAB = event.get("snapshot", self.DATA_IOTLAB)
            self.data_version = version
        self.context = copy.deepcopy(event)
        self.context.update(stock_success=False, last_patient=None, last_delivery=None)
        try:
            handler()
        finally:
            self.context = None

    def run(self):
        self.ready = True
        self.emit("ready")
        while self.active:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                self._sleep(0.05)
                continue
            try:
                self.dispatch(event)
            except Exception as error:
                self.emit("error", block_uid=event.get("source_uid"), message=str(error))

    def close(self):
        self.stop()
        if not self._closed:
            self._closed = True
            self.emit("closed")

    def input(self, key):
        if self.context is None or key not in self.context:
            raise ValueError("Input '%s' hanya tersedia dalam kejadian widget terkait." % key)
        return self.context[key]

    def answer(self, key):
        answers = self.input("answers")
        if key not in answers:
            raise ValueError("Jawaban '%s' belum tersedia pada formulir ini." % key)
        return answers[key]

    def command(self, operation, **arguments):
        if not self.active:
            raise RuntimeError("Program telah berhenti.")
        request_id = uuid.uuid4().hex
        with self._lock:
            self.pending.add(request_id)
        self.emit("command", request_id=request_id, operation=operation, arguments=arguments)
        deadline = time.monotonic() + 15
        while self.active and time.monotonic() < deadline:
            if request_id in self.results:
                with self._lock:
                    result = self.results.pop(request_id)
                    self.pending.discard(request_id)
                version = result.get("snapshot_version", self.data_version)
                if "snapshot" in result and version >= self.data_version:
                    self.DATA_IOTLAB, self.data_version = result["snapshot"], version
                if result.get("uncertain"):
                    self.active = False
                    raise RuntimeError("Hasil penyimpanan belum pasti. Periksa data sebelum menjalankan ulang.")
                if not result.get("ok"):
                    self.emit("error", message=result.get("message", "Pencatatan gagal."))
                    if operation != "record_stock":
                        raise ValueError(result.get("message", "Pencatatan gagal."))
                return result
            self._sleep(0.05)
        self.pending.discard(request_id)
        self.active = False
        raise TimeoutError("Konfirmasi belum diterima. Periksa data sebelum mengulang transaksi.")

    def medicine(self):
        try:
            barcode = self.input("barcode")
        except ValueError:
            return None
        return next((r for r in self.DATA_IOTLAB.get("obat", []) if r.get("barcode") == barcode), None)

    def is_medicine_recognized(self):
        return self.medicine() is not None

    def get_medicine_name(self):
        return (self.medicine() or {}).get("nama", "Tidak dikenal")

    def get_medicine_category(self):
        return (self.medicine() or {}).get("kategori", "")

    def get_medicine_stock(self):
        medicine = next((r for r in self.DATA_IOTLAB.get("obat", []) if r.get("barcode") == self.input("barcode")), None)
        if medicine is None:
            raise ValueError("Barcode obat belum dikenal.")
        return medicine.get("stok", 0)

    def get_scan_mode(self):
        return self.input("mode")

    def set_scan_mode(self, mode):
        self.input("barcode")
        self.context["mode"] = mode  # Compatibility for a saved legacy block.

    def record_medicine_stock(self, qty=None, task=None):
        arguments = dict(barcode=self.input("barcode"), mode=self.get_scan_mode(),
                         qty=self.input("jumlah") if qty is None else qty)
        if task is not None:
            arguments["task"] = task
        result = self.command("record_stock", **arguments)
        self.context["stock_success"] = result.get("ok", False)
        return self.context["stock_success"]

    def create_delivery(self, patient, barcode, qty=1, room="Ruang Pemeriksaan"):
        result = self.command("create_delivery", patient=patient, barcode=barcode, qty=qty, room=room)
        if self.context is not None:
            self.context["last_delivery"] = result["value"]
        return result["value"]

    def get_last_delivery(self):
        if not self.context or self.context.get("last_delivery") is None:
            raise ValueError("Belum ada tugas pengiriman dalam kejadian ini.")
        return self.context["last_delivery"]

    def _find_delivery(self, task):
        if task is None:
            if self.context and self.context.get("last_delivery"):
                task = self.context["last_delivery"]
            else:
                return None
        target_id = task.get("id") if isinstance(task, dict) else str(task)
        for row in self.DATA_IOTLAB.get("pengiriman", []):
            if str(row.get("id")) == target_id:
                return row
        return None

    def dispatch_delivery(self, task=None):
        if task is None and self.context and self.context.get("last_delivery"):
            task = self.context["last_delivery"]
        return self.command("delivery_status", task=task, status="mengirim")["value"]

    def confirm_delivery_arrival(self, task=None):
        if task is None and self.context and self.context.get("last_delivery"):
            task = self.context["last_delivery"]
        return self.command("delivery_status", task=task, status="tiba")["value"]

    def confirm_delivery_handover(self, task=None):
        if task is None and self.context and self.context.get("last_delivery"):
            task = self.context["last_delivery"]
        return self.command("delivery_status", task=task, status="diserahkan")["value"]

    def get_delivery_status(self, task=None):
        row = self._find_delivery(task)
        if row is None:
            return ""
        return row.get("status", "")

    def deliveries(self, room=None, status=None):
        rows = self.DATA_IOTLAB.get("pengiriman", [])
        if room is not None:
            rows = [r for r in rows if r.get("tujuan") == room]
        if status is not None:
            rows = [r for r in rows if r.get("status") == status]
        return sorted(rows, key=lambda r: (r.get("waktu_dibuat", ""), str(r.get("id", ""))))

    def is_stock_record_success(self):
        return bool(self.context and self.context.get("stock_success"))

    def register_patient(self, name, complaint, room):
        result = self.command("register_patient", nama=name, keluhan=complaint, tujuan=room)
        if self.context is not None:
            self.context["last_patient"] = result["value"]
        return result["value"]

    def get_last_registered_patient(self):
        if not self.context or self.context["last_patient"] is None:
            raise ValueError("Belum ada pendaftaran dalam kejadian ini.")
        return self.context["last_patient"]

    def register_medicine(self):
        return self.command("register_medicine", values=self.input("answers"))["value"]

    def record_patient_result(self, patient, result):
        return self.command("patient_result", patient=patient, hasil=result)

    def complete_patient_service(self, patient):
        return self.command("patient_complete", patient=patient)

    def queue_push(self, patient, room):
        return self.command("queue_push", patient=patient, room=room)

    def waiting(self, room, group=None):
        rows = [r for r in self.DATA_IOTLAB.get("antrean", []) if r.get("tujuan") == room
                and r.get("status") == "menunggu" and (group is None or r.get("keluhan") == group)]
        return sorted(rows, key=lambda r: (r["waktu_datang"], r["id"]))

    def queue_call_next(self, room, group):
        if not group:
            raise ValueError("Isi kelompok keluhan pada blok panggil antrean.")
        rows = self.waiting(room, group)
        if not rows:
            return None
        return self.command("queue_call", entry=rows[0]["id"])["value"]

    def queue_called_patient(self, room):
        rows = [r for r in self.DATA_IOTLAB.get("antrean", []) if r.get("tujuan") == room and r.get("status") == "dipanggil"]
        return next((p for p in self.DATA_IOTLAB.get("pasien", []) if rows and p["id"] == rows[0]["pasien"]), None)

    def queue_waiting_count(self, room):
        return len(self.waiting(room))

    def queue_is_empty(self, room):
        return not self.waiting(room)

    def filter_data(self, rows, key, value):
        key = {"Keluhan / Penyakit": "keluhan", "Nama Pasien": "nama"}.get(key, key)
        return [r for r in rows if str(r.get(key, "")) == str(value)]

    def unsupported(self, uid, capability):
        message = capability + " belum tersedia pada HAL perangkat."
        self.report(uid, "status", message)
        raise RuntimeError(message)
