import json
import os
import difflib
import wave

class TraceEvaluator:
    def __init__(self, project_root, trace_data):
        self.project_root = project_root
        self.trace = trace_data
        self.nodes = self._index_by_node()

    def _index_by_node(self):
        """Groups all trace events by node ID."""
        indexed = {}
        for event in self.trace:
            nid = event['node']
            if nid not in indexed: indexed[nid] = []
            indexed[nid].append(event)
        return indexed

    def get_node_events(self, node_id):
        return self.nodes.get(node_id, [])

    def calculate_stt_metrics(self, node_id, expected_text=None):
        """Calculates RTF and Similarity for STT nodes."""
        events = self.get_node_events(node_id)
        if not events: return {}

        start_event = next((e for e in events if e.get('type') == 'START'), None)
        finish_event = next((e for e in events if e.get('type') == 'FINISH'), None)
        in_packet = next((e for e in events if e.get('dir') == 'IN' and e.get('type') == 'input_source'), None)
        out_packet = next((e for e in events if e.get('dir') == 'OUT' and e.get('type') == 'text_final'), None)

        if not (start_event and finish_event and in_packet and out_packet):
            return {"status": "INCOMPLETE_DATA"}

        # 1. RTF Calculation
        inf_duration = finish_event['t'] - start_event['t']
        audio_path = in_packet.get('content')
        audio_duration = 1.0 # Fallback
        if audio_path and os.path.exists(os.path.join(self.project_root, audio_path)):
            try:
                with wave.open(os.path.join(self.project_root, audio_path), 'rb') as f:
                    audio_duration = f.getnframes() / float(f.getframerate())
            except: pass
        
        rtf = inf_duration / audio_duration if audio_duration > 0 else 0

        # 2. Similarity
        result_text = out_packet.get('content', '')
        similarity = 0.0
        if expected_text:
            similarity = difflib.SequenceMatcher(None, result_text.lower(), expected_text.lower()).ratio()

        return {
            "rtf": rtf,
            "similarity": similarity,
            "duration": inf_duration,
            "audio_len": audio_duration,
            "text": result_text
        }

    def calculate_llm_metrics(self, node_id):
        """Calculates TTFT and TPS for LLM nodes."""
        events = self.get_node_events(node_id)
        if not events: return {}

        start_event = next((e for e in events if e.get('type') == 'START'), None)
        out_packets = [e for e in events if e.get('dir') == 'OUT' and e.get('type') in ['text_token', 'text_final']]
        
        if not (start_event and out_packets):
            return {"status": "INCOMPLETE_DATA"}

        # 1. TTFT (Time to First Token)
        first_packet = out_packets[0]
        ttft = first_packet['t'] - start_event['t']

        # 2. TPS (Tokens Per Second)
        # For our trace, count actual text packets
        token_count = len([p for p in out_packets if p.get('type') == 'text_token'])
        if token_count == 0: token_count = 1 # Non-streaming fallback
        
        last_packet = out_packets[-1]
        total_inf_time = last_packet['t'] - start_event['t']
        tps = token_count / total_inf_time if total_inf_time > 0 else 0

        return {
            "ttft": ttft,
            "tps": tps,
            "tokens": token_count,
            "duration": total_inf_time
        }

    def calculate_tts_metrics(self, node_id):
        """Calculates CPS and RTF for TTS nodes."""
        events = self.get_node_events(node_id)
        if not events: return {}

        start_event = next((e for e in events if e.get('type') == 'START'), None)
        finish_event = next((e for e in events if e.get('type') == 'FINISH'), None)
        in_packets = [e for e in events if e.get('dir') == 'IN' and e.get('type') in ['text_token', 'text_sentence', 'text_final']]
        out_packet = next((e for e in events if e.get('dir') == 'OUT' and e.get('type') == 'audio_path'), None)

        if not (start_event and finish_event and out_packet):
            return {"status": "INCOMPLETE_DATA"}

        # 1. CPS (Characters Per Second)
        total_chars = sum([int(p.get('data_len', 0)) for p in in_packets])
        inf_duration = finish_event['t'] - start_event['t']
        cps = total_chars / inf_duration if inf_duration > 0 else 0

        # 2. Audio RTF
        audio_path = out_packet.get('content')
        audio_duration = 1.0
        if audio_path and os.path.exists(os.path.join(self.project_root, audio_path)):
            try:
                with wave.open(os.path.join(self.project_root, audio_path), 'rb') as f:
                    audio_duration = f.getnframes() / float(f.getframerate())
            except: pass
        
        rtf = inf_duration / audio_duration if audio_duration > 0 else 0

        return {
            "cps": cps,
            "rtf": rtf,
            "audio_len": audio_duration,
            "duration": inf_duration
        }
