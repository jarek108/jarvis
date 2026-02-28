from .base import NodeAdapter
from loguru import logger
import os

class SinkAdapter(NodeAdapter):
    """
    Handles 'sink' nodes (Actuators).
    Fulfills data contracts by triggering physical hardware actions at the edge.
    """
    async def run(self, node_id, node_config, input_streams, output_queue, session):
        role = node_config.get('role', 'generic_sink').lower()
        logger.info(f"🏁 Sink Node '{node_id}' ({role}) executing.")
        
        # Import edge logic (lazy load to avoid dependencies on server)
        from utils.edge_actuators import AudioActuator, KeyboardActuator, NotificationActuator
        
        async for in_id, stream in input_streams.items():
            async for packet in stream:
                content = packet.get('content')
                if not content: continue

                # 1. AUDIO PLAYBACK
                if role == "audio_playback":
                    if isinstance(content, str) and os.path.exists(content):
                        # Play from file path
                        import soundfile as sf
                        import sounddevice as sd
                        data, fs = sf.read(content)
                        sd.play(data, fs)
                        sd.wait()
                    
                # 2. KEYBOARD EMULATION
                elif role == "keyboard_typer":
                    typer = KeyboardActuator()
                    typer.type_text(str(content))

                # 3. SYSTEM NOTIFICATION
                elif role == "system_notification":
                    notifier = NotificationActuator()
                    notifier.notify("Jarvis", str(content))

                # Still put in output queue for tracing
                await output_queue.put(packet)
