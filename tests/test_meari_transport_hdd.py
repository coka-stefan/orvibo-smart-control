"""Ordinary HDD HTTP/VVP vectors, strict results and connected transport tests."""
from __future__ import annotations

import base64
import hashlib
import json
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_meari_transport_continuous as continuous
from test_meari_transport_worker import WORKER, context, H264

HDD = WORKER._hdd_protocol()


def hdd_context(operation="month", date="202610"):
    raw = context()
    raw["hdd"] = {"operation": operation, "date": date}
    return raw


def reply(body, *, code=200):
    return json.dumps({"http_code": code, "http_result": json.dumps(body)}).encode()


def playback_frame(payload, sequence=1, *, iframe=True):
    data = bytearray(continuous.frame(payload, sequence, iframe=iframe))
    data[23 if iframe else 15] = 2
    return bytes(data)


def end_frame(kind=0xFA, stream_type=2):
    data=bytearray(60 if kind in (0xFC,0xFE) else 52)
    data[:4]=b"\x00\x00\x01"+bytes([kind])
    data[23 if kind in (0xFC,0xFE) else 15]=stream_type
    struct.pack_into("<I",data,28 if kind in (0xFC,0xFE) else 20,0xFFB)
    return bytes(data)


class WireTests(unittest.TestCase):
    def test_calendar_validation_rejects_bad_dates_modes_and_extra_fields(self):
        for value in ({"operation":"month","date":"202613"}, {"operation":"day","date":"20260229"},
                      {"operation":"playback","date":"20261015096000"}, {"operation":"playback","date":"1760000000"},
                      {"operation":"seek","date":"20261015090000"}, {"operation":"day","date":"20261015","url":"http://private"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                HDD.validate_request(value)
        self.assertEqual(HDD.validate_request({"operation":"day","date":"20240229"})["date"], "20240229")

    def test_month_http_contains_complete_json_and_full_basic_password(self):
        raw = hdd_context()
        packet = HDD.search_packet(raw, 7)
        self.assertEqual(struct.unpack_from(">IIII", packet), (HDD.MAGIC, 1, 7, 0x8000))
        self.assertEqual(struct.unpack_from(">I", packet, 48)[0], len(packet) - 52)
        header, body = packet[52:].split(b"\r\n\r\n", 1)
        self.assertTrue(header.startswith(b"POST /devices/record/search_by_month HTTP/1.0\r\n"))
        basic = b"Authorization: Basic " + base64.b64encode(("admin:" + raw["device"]["hostKey"]).encode())
        self.assertIn(basic, header)
        self.assertIn(f"Content-Length: {len(body)}".encode(), header)
        self.assertEqual(json.loads(body), {"action":"POST","rec_type":0,"videoid":7,"month":"202610","deviceurl":"http://127.0.0.1/devices/record/search_by_month"})
        parts = ["admin",raw["device"]["hostKey"][:16],str(HDD.MAGIC),"7",str(0x8000),str(len(packet)-52),"meari.p2p.ppcs","00000000000123456789"]
        self.assertEqual(packet[16:48], hashlib.md5("|".join(parts).encode()).hexdigest().encode())

    def test_day_request_uses_version_zero_and_actual_channel(self):
        packet = HDD.search_packet(hdd_context("day", "20261015"), 0)
        body = json.loads(packet[52:].split(b"\r\n\r\n", 1)[1])
        self.assertEqual((body["version"], body["day"], body["videoid"]), (0, "20261015", 7))

    def test_ordinary_playback_start_and_stop_exact_76_byte_tail(self):
        raw = hdd_context("playback", "20261015091234")
        start, stop = HDD.playback_packet(raw, 3), HDD.playback_packet(raw, 4, stop=True)
        self.assertEqual((len(start), len(stop)), (76, 76))
        self.assertEqual(struct.unpack_from(">I", start, 12)[0], 0x131A)
        self.assertEqual(struct.unpack_from(">I", start, 48)[0], 24)
        self.assertEqual(start[52:], bytes.fromhex("070000001000000000000000ea070a0f00090c2201020000"))
        self.assertEqual(stop[52:], bytes.fromhex("070000000100000000000000000000000000000000000000"))
        self.assertNotEqual(start[16:48], stop[16:48])

    def test_storage_card_month_day_and_playback_packets_use_zero_channel(self):
        for operation, date in (("month", "202610"), ("day", "20261015")):
            raw = hdd_context(operation, date)
            raw["device"].update(devTypeID=2, nvrChannelId=0)
            raw["channel_id"] = 0
            packet = HDD.search_packet(WORKER.validate_context(raw), 0)
            body = json.loads(packet[52:].split(b"\r\n\r\n", 1)[1])
            self.assertEqual((body["videoid"], body["rec_type"]), (0, 0))
            self.assertEqual(body[operation], date)
            if operation == "day":
                self.assertEqual(body["version"], 0)
        raw = hdd_context("playback", "20261015091234")
        raw["device"].update(devTypeID=2, nvrChannelId=0)
        raw["channel_id"] = 0
        raw = WORKER.validate_context(raw)
        self.assertEqual(HDD.playback_packet(raw, 0)[52:], bytes.fromhex("000000001000000000000000ea070a0f00090c2201020000"))
        self.assertEqual(HDD.playback_packet(raw, 1, stop=True)[52:], bytes.fromhex("000000000100000000000000000000000000000000000000"))

    def test_reply_reassembly_discards_old_sequence_and_rejects_newer(self):
        raw = hdd_context()
        parser = HDD.ReplyBuffer(7)
        old, current = HDD.packet(raw, 0x8000, 6, b"old"), HDD.packet(raw, 0x8000, 7, b"new")
        self.assertIsNone(parser.feed(old))
        for part in (current[:2], current[2:10], current[10:53]):
            self.assertIsNone(parser.feed(part))
        self.assertEqual(parser.feed(current[53:]), b"new")
        with self.assertRaisesRegex(ValueError,"sequence"):
            HDD.ReplyBuffer(7).feed(HDD.packet(raw,0x8000,8,b"newer"))

    def test_reply_rejects_excessive_length_and_ignores_media(self):
        parser = HDD.ReplyBuffer(0)
        self.assertIsNone(parser.feed(continuous.frame(H264)))
        packet = bytearray(HDD.packet(hdd_context(),0x8000,0,b""))
        struct.pack_into(">I",packet,48,HDD.MAX_REPLY_BYTES+1)
        with self.assertRaisesRegex(ValueError,"limit"):
            parser.feed(packet)


class RecordingListTests(unittest.TestCase):
    def test_month_flags_are_presence_by_index_with_calendar_month_bound(self):
        result = HDD.parse_search_reply(reply([1,0,"1",True]+[0]*24+[1,1,1]), {"operation":"month","date":"202602"})
        self.assertEqual(result["recording_days"], ["20260201","20260203"])
        self.assertEqual(result["recording_count"], 2)
        self.assertNotIn("http_result", result)

    def test_day_fragments_return_device_calendar_times_and_reject_invalid_rows(self):
        result = HDD.parse_search_reply(reply(["091234-092015","235959-235959","246000-246100","TOKEN-SECRET",None]), {"operation":"day","date":"20261015"})
        self.assertEqual(result["fragments"], [{"start":"20261015091234","end":"20261015092015"}])
        self.assertEqual(result["invalid_fragment_count"],4)
        self.assertNotIn("SECRET",json.dumps(result))

    def test_large_valid_result_is_bounded_and_explicitly_truncated(self):
        result = HDD.parse_search_reply(reply(["091234-092015"]*300), {"operation":"day","date":"20261015"})
        self.assertEqual(len(result["fragments"]),256)
        self.assertEqual(result["recording_count"],300)
        self.assertTrue(result["fragments_truncated"])
        self.assertLess(len(json.dumps(result)),49152)

    def test_failed_or_wrong_shape_device_response_never_passes_through(self):
        for payload in (reply([],code=403), b"HTTP/1.0 200 OK\r\n", b'{"http_code":200,"http_result":{"PRIVATE":1}}', reply({"PRIVATE":1})):
            with self.subTest(payload=payload), self.assertRaises((ValueError,TypeError)):
                HDD.parse_search_reply(payload,{"operation":"day","date":"20261015"})


class ConnectedHddTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = WORKER.load_protocol()

    def connect(self, raw, payloads):
        from vendor.kcp_tunnel import build_iva_data_frame
        transport = continuous.ContinuousTransportTests()
        transport.lib = self.lib
        fake, clock, instances, sent = transport.transport(frames=0)
        index = [0]

        def receive(*args, **kwargs):
            clock[0] += 1
            if index[0] >= len(payloads):
                return []
            payload = payloads[index[0]]
            index[0] += 1
            return [SimpleNamespace(data=build_iva_data_frame(payload),peer=("192.0.2.2",9101),source=("192.0.2.1",9100),via_turn=True,stun=None)]

        fake.recv_peer_packets = receive
        output, stages = [], []
        kwargs = {"frame_output":lambda data,summary:output.append(data)} if raw["hdd"]["operation"] == "playback" else {}
        with patch.object(WORKER.time,"monotonic",side_effect=lambda:clock[0]), patch.object(WORKER,"MAX_STREAM_SECONDS",8), patch.object(WORKER,"STREAM_IDLE_SECONDS",2):
            result = WORKER.run_probe(raw,stages.append,library=fake,**kwargs)
        commands=[]
        for packet in sent:
            offset=packet.find(struct.pack(">I",HDD.MAGIC))
            if offset>=0:
                commands.append(packet[offset:])
        self.assertTrue(all(item.closed for item in instances))
        return result, list(dict.fromkeys(commands)), output, stages

    def test_month_query_uses_connected_tunnel_without_opening_live_stream(self):
        raw=hdd_context()
        response=HDD.packet(raw,0x8000,0,reply([1,0,1]))
        (stage,summary),commands,output,stages=self.connect(raw,[response])
        self.assertEqual(stage,"hdd_search_received")
        self.assertEqual(summary["recording_days"],["20261001","20261003"])
        self.assertEqual([struct.unpack_from(">I",packet,12)[0] for packet in commands],[0x8000])
        self.assertEqual(output,[])

    def test_query_timeout_is_finite_and_cleanup_does_not_send_live_stop(self):
        (stage,_),commands,_,_=self.connect(hdd_context(),[])
        self.assertEqual(stage,"hdd_search_timeout")
        self.assertEqual(len(commands),1)

    def test_playback_ack_precedes_encoded_frames_and_stop_uses_playback_command(self):
        raw=hdd_context("playback","20261015091234")
        ack=HDD.packet(raw,0x131A,0,b"")
        video=playback_frame(H264)
        (stage,summary),commands,output,stages=self.connect(raw,[ack,video,playback_frame(b"\x00\x00\x01\x41\x9a\x80",2,iframe=False)])
        self.assertEqual(stage,"stream_idle_timeout")
        self.assertTrue(summary["playback_requested"])
        self.assertTrue(summary["playback_acknowledged"])
        self.assertFalse(summary["decoded"])
        self.assertEqual(len(output),2)
        self.assertIn("hdd_playback_acknowledged",stages)
        self.assertEqual([struct.unpack_from(">I",packet,12)[0] for packet in commands],[0x131A,0x131A])
        self.assertEqual(struct.unpack_from("<I",commands[-1],56)[0],1)

    def test_storage_card_connected_queries_and_history_stream(self):
        for operation, date, body in (("month", "202610", [1, 0, 1]),
                                      ("day", "20261015", ["091234-092015"])):
            raw = hdd_context(operation, date)
            raw["device"].update(devTypeID=2, nvrChannelId=0)
            raw["channel_id"] = 0
            raw = WORKER.validate_context(raw)
            (stage, summary), commands, output, _ = self.connect(raw, [HDD.packet(raw, 0x8000, 0, reply(body))])
            self.assertEqual(stage, "hdd_search_received")
            self.assertGreater(summary["recording_count"], 0)
            self.assertEqual(output, [])
            query = json.loads(commands[0][52:].split(b"\r\n\r\n", 1)[1])
            self.assertEqual(query["videoid"], 0)
        raw = hdd_context("playback", "20261015091234")
        raw["device"].update(devTypeID=2, nvrChannelId=0)
        raw["channel_id"] = 0
        raw = WORKER.validate_context(raw)
        for video, expected_frames in ((continuous.frame(H264), 0), (playback_frame(H264), 1)):
            (stage, summary), commands, output, _ = self.connect(raw, [HDD.packet(raw, 0x131A, 0, b""), video, end_frame(stream_type=0)])
            self.assertEqual(len(output), expected_frames)
            self.assertEqual(summary["keyframe_received"], bool(expected_frames))
            for packet in commands:
                self.assertEqual(struct.unpack_from("<I", packet, 52)[0], 0)
            self.assertEqual(struct.unpack_from("<I", commands[-1], 56)[0], 1)

    def test_ack_without_video_cannot_confirm_playback(self):
        raw=hdd_context("playback","20261015091234")
        (stage,summary),_,output,_=self.connect(raw,[HDD.packet(raw,0x131A,0,b"")])
        self.assertEqual(stage,"no_video_frame")
        self.assertTrue(summary["playback_acknowledged"])
        self.assertFalse(summary["keyframe_received"])
        self.assertEqual(output,[])

    def test_live_frames_cannot_confirm_history_even_after_ack(self):
        raw=hdd_context("playback","20261015091234")
        live=bytearray(continuous.frame(H264))
        live[23]=1
        (stage,summary),_,output,_=self.connect(raw,[HDD.packet(raw,0x131A,0,b""),bytes(live)])
        self.assertEqual(stage,"no_video_frame")
        self.assertFalse(summary["keyframe_received"])
        self.assertEqual(output,[])

    def test_native_playback_end_marker_closes_finite_stream_and_sends_stop(self):
        raw=hdd_context("playback","20261015091234")
        (stage,summary),commands,output,stages=self.connect(raw,[HDD.packet(raw,0x131A,0,b""),playback_frame(H264),end_frame(stream_type=0)])
        self.assertEqual(stage,"stream_complete")
        self.assertTrue(summary["playback_end_received"])
        self.assertEqual(len(output),1)
        self.assertIn("hdd_playback_ended",stages)
        self.assertEqual(struct.unpack_from("<I",commands[-1],56)[0],1)

    def test_end_header_precedes_mode_validation_for_acknowledged_playback(self):
        for kind in (0xFC,0xFD,0xFA,0xFE):
            for mode in (0,1,2):
                with self.subTest(kind=kind,mode=mode):
                    observation=WORKER.Observation(self.lib)
                    observation.playback_requested=True
                    observation.playback_acknowledged=True
                    observation.feed(end_frame(kind,mode))
                    self.assertTrue(observation.playback_end_received)

    def test_end_marker_requires_active_playback_and_complete_extended_header(self):
        for kind in (0xFC,0xFD,0xFA,0xFE):
            for requested, acknowledged in ((False,False),(False,True),(True,False)):
                with self.subTest(kind=kind,requested=requested,acknowledged=acknowledged):
                    observation=WORKER.Observation(self.lib)
                    observation.playback_requested=requested
                    observation.playback_acknowledged=acknowledged
                    observation.feed(end_frame(kind,0))
                    self.assertFalse(observation.playback_end_received)
            with self.subTest(kind=kind,truncated=True):
                observation=WORKER.Observation(self.lib)
                observation.playback_requested=True
                observation.playback_acknowledged=True
                observation.feed(end_frame(kind,0)[:-1])
                self.assertFalse(observation.playback_end_received)

    def test_unspecified_media_mode_cannot_confirm_history_after_ack(self):
        raw=hdd_context("playback","20261015091234")
        unspecified=bytearray(continuous.frame(H264))
        unspecified[23]=0
        (stage,summary),_,output,_=self.connect(raw,[HDD.packet(raw,0x131A,0,b""),bytes(unspecified)])
        self.assertEqual(stage,"no_video_frame")
        self.assertFalse(summary["keyframe_received"])
        self.assertFalse(summary["playback_end_received"])
        self.assertEqual(output,[])

    def test_end_marker_before_ack_does_not_complete_playback(self):
        raw=hdd_context("playback","20261015091234")
        (stage,summary),commands,output,stages=self.connect(raw,[end_frame(stream_type=0)])
        self.assertEqual(stage,"hdd_playback_timeout")
        self.assertFalse(summary["playback_acknowledged"])
        self.assertFalse(summary["playback_end_received"])
        self.assertNotIn("hdd_playback_ended",stages)
        self.assertEqual(output,[])
        self.assertEqual(struct.unpack_from("<I",commands[-1],56)[0],1)


if __name__ == "__main__":
    unittest.main()
