from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta

HOST = "0.0.0.0"
PORT = 8080

class MIPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 1. Read headers sent by MeOS MIP client
        competition_id = self.headers.get("competition", "1")
        last_id = int(self.headers.get("lastid", "0"))

        # 2. Check if MeOS has already received these items
        # Each item (entry, punch) gets a sequential id.
        entry_id = 101
        item_ids = [entry_id] + list(range(102, 107))
        last_item_id = item_ids[-1]

        if last_id < last_item_id:
            xml_response = self.create_mip_xml(entry_id, item_ids)
            new_lastid = last_item_id
        else:
            # Nothing new to send to MeOS
            xml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<MIPData xmlns="http://www.melin.nu/mip" lastid="{last_id}">
</MIPData>"""

        # 3. Return response to MeOS
        response_bytes = xml_response.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def create_mip_xml(self, entry_id, item_ids):
        classname, card, bib, name = "H21", 8123456, "42", "Dupont, Jean"

        # Punch time = tenths of a second after 00:00:00 of competition day
        def tenths(dt):
            midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return int((dt - midnight).total_seconds() * 10)

        now = datetime.now().replace(microsecond=0)
        start_t = tenths(now)
        punches = "".join(
            f'  <p id="{_id}" code="{code}" card="{card}" time="{tenths(now + timedelta(minutes=offset))}"/>\n'
            for _id, code, offset in (
                (item_ids[1], "201", 5),
                (item_ids[2], "202", 7),
                (item_ids[3], "203", 9),
                (item_ids[4], "204", 11),
            )
        )
        punches += f'  <p id="{item_ids[5]}" type="finish" code="300" card="{card}" time="{tenths(now + timedelta(minutes=13))}"/>\n'

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<MIPData xmlns="http://www.melin.nu/mip" lastid="{item_ids[-1]}">
  <entry id="{entry_id}" classname="{classname}" paid="true">
    <name birthyear="1995">{name}</name>
    <club>Club Orientation</club>
    <card hired="false">{card}</card>
    <bib>{bib}</bib>
  </entry>
  <p id="{item_ids[0]}" type="start" card="{card}" time="{start_t}"/>
{punches}</MIPData>"""


def run_server():
    server = HTTPServer((HOST, PORT), MIPRequestHandler)
    print(f"MIP Server running on http://{HOST}:{PORT}")
    print("In MeOS: Configure 'Online Input' with this URL.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
        server.server_close()


if __name__ == "__main__":
    run_server()