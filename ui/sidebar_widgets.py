import os
import customtkinter as ctk
from loguru import logger

class LoadingSpinner(ctk.CTkCanvas):
    def __init__(self, master, colors, size=30, **kwargs):
        # Canvas doesn't support 'transparent', must use actual color
        bg_color = "#0B0F19"
        try:
            # Try to get master's fg_color (for CTk frames) or bg
            for attr in ["fg_color", "bg"]:
                if hasattr(master, "cget"):
                    val = master.cget(attr)
                    if val and val != "transparent":
                        bg_color = val
                        break
        except: pass
        
        super().__init__(master, width=size, height=size, bg=bg_color, highlightthickness=0, **kwargs)
        self.colors = colors
        self.size = size
        self.angle = 0
        self.is_running = False
        self._draw_arc()
        self.bind("<Configure>", lambda e: self._draw_arc())

    def _draw_arc(self):
        if not self.winfo_exists(): return
        self.delete("all")
        # Draw a subtle background circle (always visible)
        padding = 4
        self.create_oval(padding, padding, self.size-padding, self.size-padding, outline="#1A202C", width=2)
        
        # Draw the spinning arc only if running
        if self.is_running:
            self.create_arc(padding, padding, self.size-padding, self.size-padding, 
                            start=self.angle, extent=120, outline=self.colors.get('accent', '#00CF91'), 
                            width=3, style="arc")
        
    def animate(self):
        if not self.is_running or not self.winfo_exists(): return
        self.angle = (self.angle + 10) % 360
        self._draw_arc()
        self.after(30, self.animate)

    def start(self):
        if not self.winfo_exists() or self.is_running: return
        self.is_running = True
        self.animate()

    def stop(self):
        self.is_running = False
        if self.winfo_exists():
            self._draw_arc() # Redraw one last time to show only the background circle

class VramMonitor(ctk.CTkFrame):
    def __init__(self, master, colors, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.colors = colors
        
        self.pack(pady=(5, 0), fill="x")
        
        # Line 1: VRAM total: [Total] GB ([Percent]% used)
        self.line1 = ctk.CTkFrame(self, fg_color="transparent")
        self.line1.pack(fill="x")
        
        ctk.CTkLabel(self.line1, text="VRAM total: ", font=("Consolas", 11), text_color="#D0D0D0").pack(side="left")
        self.v_lbl_total = ctk.CTkLabel(self.line1, text="0.0 GB", font=("Consolas", 11, "bold"), text_color="#FFFFFF")
        self.v_lbl_total.pack(side="left")
        
        self.v_lbl_total_pct = ctk.CTkLabel(self.line1, text="(0% used)", font=("Consolas", 10), text_color="#A0A0A0")
        self.v_lbl_total_pct.pack(side="left", padx=(5, 0))

        # Line 2: Used: [Used] GB ([Int] int., [Ext] ext.)
        self.line2 = ctk.CTkFrame(self, fg_color="transparent")
        self.line2.pack(fill="x", pady=(0, 2))
        
        ctk.CTkLabel(self.line2, text="Used: ", font=("Consolas", 10), text_color="#D0D0D0").pack(side="left")
        self.v_lbl_used = ctk.CTkLabel(self.line2, text="0.0 GB", font=("Consolas", 10, "bold"), text_color="#FFFFFF")
        self.v_lbl_used.pack(side="left")
        
        self.v_lbl_breakdown = ctk.CTkLabel(self.line2, text="", font=("Consolas", 9), text_color="#A0A0A0")
        self.v_lbl_breakdown.pack(side="left", padx=(5, 0))

        # Visual Bar
        self.bar_bg = ctk.CTkFrame(self, width=200, height=8, fg_color="#10141B", corner_radius=4)
        self.bar_bg.pack(pady=(2, 10), padx=10)
        self.bar_ext = ctk.CTkFrame(self.bar_bg, width=0, height=8, fg_color=self.colors.get('warning'), corner_radius=4)
        self.bar_ext.place(x=0, y=0)
        self.bar_model = ctk.CTkFrame(self.bar_bg, width=0, height=8, fg_color=self.colors.get('accent'), corner_radius=4)
        self.bar_model.place(x=0, y=0)

    def update(self, used, total, external=None):
        pct = used / total if total > 0 else 0
        self.v_lbl_total.configure(text=f"{total:.1f} GB")
        self.v_lbl_total_pct.configure(text=f"({int(pct*100)}% used)")
        
        self.v_lbl_used.configure(text=f"{used:.1f} GB")

        bar_max_w = 200

        if external is None:
            # SIMPLE MODE: Hide breakdown
            self.v_lbl_breakdown.configure(text="")
            self.bar_ext.configure(width=0)
            self.bar_model.place(x=0, y=0)
            self.bar_model.configure(width=pct * bar_max_w)
        else:
            # DETAILED MODE: Show breakdown
            if used < external: external = used
            model_vram = max(0, used - external)
            
            # (0.1 int., 2.4 ext.) - No GB labels here as requested
            breakdown_text = f"({model_vram:.1f} int., {external:.1f} ext.)"
            self.v_lbl_breakdown.configure(text=breakdown_text)

            ext_w = (external / total) * bar_max_w if total > 0 else 0
            model_w = (model_vram / total) * bar_max_w if total > 0 else 0
            ext_w = min(bar_max_w, ext_w)
            model_w = min(bar_max_w - ext_w, model_w)
            
            self.bar_ext.configure(width=ext_w)
            self.bar_model.place(x=ext_w, y=0)
            self.bar_model.configure(width=model_w)
        
        if pct > 0.95: self.bar_model.configure(fg_color=self.colors.get('error'))
        elif pct > 0.85: self.bar_model.configure(fg_color=self.colors.get('warning'))
        else: self.bar_model.configure(fg_color=self.colors.get('accent'))

class ModelHealthCard(ctk.CTkFrame):
    def __init__(self, master, model_data, colors, on_click, on_right_click, **kwargs):
        super().__init__(master, fg_color="#12161E", corner_radius=6, cursor="hand2", border_width=0, **kwargs)
        self.model_data = model_data
        self.colors = colors
        self.mid = model_data['id']
        
        self.pack(fill="x", pady=6, padx=5)
        
        # Events
        self.bind("<Button-1>", lambda e: on_click(self.mid))
        self.bind("<Button-3>", lambda e: on_right_click(e, model_data))
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        
        # Header
        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.pack(fill="x", padx=8, pady=(8, 0))
        self.header.bind("<Button-1>", lambda e: on_click(self.mid))
        self.header.bind("<Button-3>", lambda e: on_right_click(e, model_data))

        self.lamp = ctk.CTkLabel(self.header, text="●", font=("Arial", 18), text_color=self.colors.get('gray'))
        self.lamp.pack(side="left", padx=(0, 5))
        self.lamp.bind("<Button-1>", lambda e: on_click(self.mid))

        self.name_box = ctk.CTkTextbox(self.header, font=("Consolas", 12, "bold"), height=25, fg_color="transparent", text_color="#FFFFFF", border_width=0, activate_scrollbars=False)
        self.name_box.insert("1.0", self.mid)
        self.name_box.configure(state="disabled")
        self.name_box.pack(side="left", fill="x", expand=True)
        self.name_box.bind("<Button-1>", lambda e: on_click(self.mid))

        # Capabilities
        caps = model_data.get('capabilities', [])
        inputs = [c.replace("_in", "") for c in caps if c.endswith("_in")]
        outputs = [c.replace("_out", "") for c in caps if c.endswith("_out")]
        
        self.subtext = ctk.CTkLabel(self, text=f"IN: {', '.join(inputs)} | OUT: {', '.join(outputs)}", font=("Consolas", 10), text_color="#D0D0D0", anchor="w")
        self.subtext.pack(fill="x", padx=28, pady=(0, 2))

        # Engine & Streaming
        self.stream_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.stream_frame.pack(fill="x", padx=28, pady=(0, 2))
        
        is_llm = model_data['engine'] in ['ollama', 'vllm']
        streaming = model_data.get('params', {}).get('stream', True if is_llm else False)
        
        ctk.CTkLabel(self.stream_frame, text=f"{model_data['engine'].upper()} • Out-Stream: ", font=("Consolas", 10), text_color="#B0B0B0").pack(side="left")
        self.s_lamp = ctk.CTkLabel(self.stream_frame, text="●", font=("Arial", 12), text_color=(self.colors.get('success') if streaming else self.colors.get('error')))
        self.s_lamp.pack(side="left")

        # Params
        params_dict = model_data.get('params', {}).copy()
        params_dict.pop('device', None)
        params_dict.pop('stream', None)
        if params_dict:
            p_str = " ".join([f"{k}:{v}" for k, v in params_dict.items()])
            self.params_box = ctk.CTkTextbox(self, font=("Consolas", 9), height=35, fg_color="transparent", text_color="#A0A0A0", border_width=0, activate_scrollbars=False)
            self.params_box.insert("1.0", p_str)
            self.params_box.configure(state="disabled")
            self.params_box.pack(fill="x", padx=28, pady=(0, 8))
        else:
            ctk.CTkLabel(self, text="", height=4).pack()

    def set_status(self, status):
        color = self.colors.get('gray')
        if status == "ON": color = self.colors.get('success')
        elif status == "OFF": color = self.colors.get('error')
        elif status == "STARTUP": color = self.colors.get('warning')
        elif status == "BUSY": color = self.colors.get('accent')
        elif status == "ORPHAN": color = "#505050"
        self.lamp.configure(text_color=color)

    def set_orphan(self, is_orphan):
        if is_orphan:
            self.lamp.configure(text_color="#505050")
            self.subtext.configure(text_color="#606060")
            self.name_box.configure(text_color="#808080")
            # Add small indicator
            try: self.orphan_lbl.destroy()
            except: pass
            self.orphan_lbl = ctk.CTkLabel(self.header, text="[NOT IN USE]", font=("Consolas", 9), text_color="#606060")
            self.orphan_lbl.pack(side="right", padx=5)
        else:
            self.subtext.configure(text_color="#D0D0D0")
            self.name_box.configure(text_color="#FFFFFF")
            try: self.orphan_lbl.destroy()
            except: pass

    def set_selected(self, selected):
        if selected:
            self.configure(border_width=2, border_color=self.colors.get('success'), fg_color="#1A202C")
        else:
            self.configure(border_width=0, fg_color="#12161E")

    def _on_enter(self, event):
        # We don't have easy access to app.selected_mid here without passing it or using a callback
        # For now, just a simple hover effect if not already selected (visual only)
        if self.cget("border_width") == 0:
            self.configure(fg_color="#1A202C")

    def _on_leave(self, event):
        if self.cget("border_width") == 0:
            self.configure(fg_color="#12161E")
