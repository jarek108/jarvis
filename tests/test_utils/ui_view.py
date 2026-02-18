    def make_progress_view(self):
        """Renders the hierarchical domain/model list with clickable log links."""
        table = Table.grid(padding=(0, 1), expand=True)
        
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        session_path = os.path.join(project_root, "tests", "logs", self.session_id)

        for d_name, d_data in self.test_data.items():
            d_status = d_data['status'].lower()
            d_color = "green" if d_status == "passed" else ("red" if d_status == "failed" else ("blue" if d_status == "wip" else "bright_black"))
            
            d_dur = d_data['duration'] or (time.perf_counter() - d_data['start_time'] if d_data['start_time'] else 0)
            
            # Aggregate timers for domain
            d_stp, d_exe, d_cln = 0, 0, 0
            for l_data in d_data['loadouts'].values():
                d_stp += self.get_phase_time(l_data, "setup")
                d_exe += self.get_phase_time(l_data, "execution")
                d_cln += self.get_phase_time(l_data, "cleanup")

            # Domain Row: NAME - TIME, (A/B models) (C/D scenarios) - stp: Xs, exec: Ys, cln: Zs
            models_total = len(d_data['loadouts'])
            d_text = Text.assemble(
                (f"â€¢ {d_name.upper()}", f"bold {d_color}"),
                (f" - {d_dur:.1f}s", d_color),
                (f" ({d_data['models_done']}/{models_total} models)", "white"),
                (f" ({d_data['done']}/{d_data['total']} scenarios)", "white"),
                (f" - stp: {d_stp:.1f}s, exec: {d_exe:.1f}s, cln: {d_cln:.1f}s", "gray50")
            )
            table.add_row(d_text)
            
            for l_name, l_data in d_data['loadouts'].items():
                l_status = l_data['status'].lower()
                l_color = "green" if l_status == "passed" else ("red" if l_status == "failed" else ("blue" if l_status == "wip" else "bright_black"))
                stp = self.get_phase_time(l_data, "setup")
                exe = self.get_phase_time(l_data, "execution")
                cln = self.get_phase_time(l_data, "cleanup")
                
                # Model Row: Indented
                l_text = Text("   ➤ ")
                
                # Split multi-model names (e.g., STT + LLM + TTS)
                models = l_data.get('models', [l_name])
                log_paths = l_data.get('log_paths', {})
                
                for i, m in enumerate(models):
                    if i > 0: l_text.append(" + ", style="white")
                    
                    if l_status == "pending":
                        l_text.append(m, style=l_color)
                    else:
                        m_lower = m.lower()
                        m_type = "llm" if any(x in m_lower for x in ["ol_", "vl_", "vllm:"]) else 
                                 ("stt" if "whisper" in m_lower else 
                                 ("tts" if "chatterbox" in m_lower else None))
                        
                        target_path = log_paths.get(m_type) or log_paths.get("sts") or session_path
                        url = f"file:///{target_path.replace(os.sep, '/')}"
                        l_text.append(m, style=f"{l_color} link {url}")

                l_text.append(f" ({l_data['done']}/{l_data['total']})", style="white")
                l_text.append(f" - stp: {stp:.1f}s, exec: {exe:.1f}s, cln: {cln:.1f}s", style="gray70")
                
                if l_status == "passed":
                    l_text.append(" [PASSED]", style="bold green")
                elif l_data.get('error_message'):
                    l_text.append(f" [{l_data['error_message']}]", style="bold red")
                elif l_status == "failed" or l_data.get('errors', 0) > 0:
                    l_text.append(f" [{l_data['errors']} FAILED]", style="bold red")
                table.add_row(l_text)
        return table
