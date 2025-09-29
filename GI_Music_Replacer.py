import customtkinter
from tkinter import filedialog, messagebox
import os
import re
import struct
import sys
import concurrent.futures
import shutil
from io import BufferedReader, BytesIO
from FilePackager import Package, build_pck_file

def process_single_bank_file(bank_file_path, numeric_ids):
    found_offsets_in_file = {}

    try:
        with open(bank_file_path, 'rb') as f:
            content = f.read()
            
        for numeric_id in numeric_ids:
            id_bytes = struct.pack('<I', numeric_id)

            pos = -1
            while True:
                pos = content.find(id_bytes, pos + 1)
                if pos == -1:
                    break
                
                check_pos = pos + 4 + 13
                if check_pos + 4 <= len(content) and content[check_pos:check_pos + 4] == id_bytes:
                    end_offset = check_pos + 4
                    if numeric_id not in found_offsets_in_file:
                        found_offsets_in_file[numeric_id] = []
                    found_offsets_in_file[numeric_id].append(end_offset)     
    except Exception as e:
        log(f"Error: processing {os.path.basename(bank_file_path)} failed: {e}")
        return bank_file_path, None

    return bank_file_path, found_offsets_in_file


def patch_bank_file(input_path, output_path, offsets, wem_duration_ms):
    try:
        # Create a copy of the original file in the output folder
        shutil.copyfile(input_path, output_path)
        
        # Prepare the binary data
        zero_bytes = b'\x00' * 28
        duration_bytes = struct.pack('<d', wem_duration_ms)
        
        # Search patterns
        hex_pattern = b'\x48\xd6\xbb\x5b'

        with open(output_path, 'r+b') as f:
            for numeric_id, offsets_list in offsets.items():
                for offset in offsets_list:
                    # Move the file pointer at the beginning of the 32 bytes to zero
                    f.seek(offset)

                    # Writing the 32 bytes zero
                    f.write(zero_bytes)
                    
                    # Write the 8 bytes of the duration
                    f.write(duration_bytes)
                    f.seek(offset)
                    content = f.read()

                    # Find the first pattern after the offset
                    pos_in_content = content.find(hex_pattern)
                    if pos_in_content != -1:
                        pos = offset + pos_in_content  # Absolute position in the file

                        # Patch immediately after the pattern
                        f.seek(pos + len(hex_pattern))
                        f.write(duration_bytes)

                        # Patch 28 byte before the pattern, if possible
                        if pos - 28 >= 0:
                            f.seek(pos - 28)
                            f.write(duration_bytes)
                        else:
                            log(f"Info: Cannot patch at negative offset for pattern found at {pos}")
                    else:
                        log(f"Info: Pattern not found after offset {offset}")
        log(f"Info: Patched {os.path.basename(input_path)} successfully")
    except Exception as e:
        log(f"Error: Failed to patch {os.path.basename(input_path)}: {e}")


def get_wem_duration(wem_path):
    try:
        with open(wem_path, 'rb') as f:
            # Verify header RIFF and WAVE
            if f.read(4) != b'RIFF' or f.read(4) is None or f.read(4) != b'WAVE':
                raise ValueError("Invalid file selected")

            # Read samples and streamtotalsamples from their respective offsets
            f.seek(24)
            sample_rate = struct.unpack('<I', f.read(4))[0]
            f.seek(44)
            total_samples  = struct.unpack('<I', f.read(4))[0]

            # Calculate wem duration in seconds
            duration_ms = (total_samples  / sample_rate) * 1000
            return duration_ms
    except Exception as e:
        log("Error: Failed to find .Wem duration")
        return None


_logger_widget = None
_logger_buffer = []

def set_logger_widget(widget):
    global _logger_widget, _logger_buffer
    _logger_widget = widget
    for msg in _logger_buffer:
        _logger_widget.configure(state="normal")
        _logger_widget.insert("end", msg + "\n")
        _logger_widget.see("end")
        _logger_widget.configure(state="disabled")
    _logger_buffer = []


def log(message):
    global _logger_widget, _logger_buffer
    if _logger_widget:
        _logger_widget.configure(state="normal")
        _logger_widget.insert("end", message + "\n")
        _logger_widget.see("end")
        _logger_widget.configure(state="disabled")
    else:
        _logger_buffer.append(message)

customtkinter.set_appearance_mode("Dark")
customtkinter.set_default_color_theme("dark-blue")

class App(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        self.title("GI Music Replacer")
        self.geometry("600x800")
        self.resizable(False, False)
        self.pck_files = []
        self.wem_file = ""
        self.output_folder = ""
        self.id_entries = []
        self.numeric_ids = []
        self.banks_path = ""

        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(__file__)

        icon_path = os.path.join(base_path, "icon.ico")
        self.iconbitmap(icon_path)

        self.create_widgets()
        log("Info: GUI initialized")


    def create_widgets(self):
        button_color = "#ff0000"
        button_hover = "#cc0000"
        header_text = "#ffffff"
        header_font = ("Arial", 12, "bold")  

        pck_frame = customtkinter.CTkFrame(self, fg_color="black", corner_radius=5)
        pck_frame.pack(pady=5, padx=20, fill="x")

        customtkinter.CTkLabel(
            pck_frame, text="Musics.PCK Files:", text_color=header_text, font=("Arial", 14, "bold")
        ).pack(anchor="w", padx=10, pady=(3, 0))

        top_pck = customtkinter.CTkFrame(pck_frame, fg_color="transparent")
        top_pck.pack(fill="x", padx=10, pady=3)

        self.pck_button = customtkinter.CTkButton(
            top_pck,
            text="Select Musics.pck File(s)",
            command=self.select_pck_files,
            fg_color=button_color,
            hover_color=button_hover,
            height=25,
            font=header_font
        )
        self.pck_button.pack(side="left", padx=(0, 10))

        self.pck_label = customtkinter.CTkLabel(
            top_pck,
            text="No Musics.pck files selected",
            justify="left",
            text_color=header_text,
            font=header_font
        )
        self.pck_label.pack(side="left", expand=True, fill="x")
        banks_frame = customtkinter.CTkFrame(self, fg_color="black", corner_radius=5)
        banks_frame.pack(pady=5, padx=20, fill="x")

        customtkinter.CTkLabel(
            banks_frame, text="Banks Folder:", text_color="#ffffff", font=("Arial", 14, "bold")
        ).pack(anchor="w", padx=10, pady=(3, 0))

        top_banks = customtkinter.CTkFrame(banks_frame, fg_color="transparent")
        top_banks.pack(fill="x", padx=10, pady=3)

        self.banks_button = customtkinter.CTkButton(
            top_banks,
            text="Select Banks Folder",
            command=self.select_banks_folder,
            fg_color="#ff0000",
            hover_color="#cc0000",
            height=25,
            font=("Arial", 12, "bold")
        )
        self.banks_button.pack(side="left", padx=(0, 10))

        self.banks_label = customtkinter.CTkLabel(
            top_banks,
            text=f"No Banks folder selected",
            justify="left",
            text_color="#ffffff",
            font=("Arial", 12, "bold")
        )
        self.banks_label.pack(side="left", expand=True, fill="x")

        wem_frame = customtkinter.CTkFrame(self, fg_color="black", corner_radius=5)
        wem_frame.pack(pady=5, padx=20, fill="x")

        customtkinter.CTkLabel(
            wem_frame, text="WEM File:", text_color=header_text, font=("Arial", 14, "bold")
        ).pack(anchor="w", padx=10, pady=(3, 0))

        top_wem = customtkinter.CTkFrame(wem_frame, fg_color="transparent")
        top_wem.pack(fill="x", padx=10, pady=3)

        self.wem_button = customtkinter.CTkButton(
            top_wem,
            text="Select .wem File",
            command=self.select_wem_file,
            fg_color=button_color,
            hover_color=button_hover,
            height=25,
            font=header_font
        )
        self.wem_button.pack(side="left", padx=(0, 10))

        self.wem_label = customtkinter.CTkLabel(
            top_wem,
            text="No .wem file selected",
            justify="left",
            text_color=header_text,
            font=header_font
        )
        self.wem_label.pack(side="left", expand=True, fill="x")

        dur_frame = customtkinter.CTkFrame(wem_frame, fg_color="transparent")
        dur_frame.pack(fill="x", padx=10, pady=(0, 3))

        customtkinter.CTkLabel(
            dur_frame, text="WEM/Audio Lenght (ms):", text_color=header_text, font=header_font
        ).pack(side="left", padx=(0, 10))

        self.wem_duration_entry = customtkinter.CTkEntry(dur_frame, width=150, height=25)
        self.wem_duration_entry.pack(side="left", expand=True, fill="x")

        self.id_main_frame = customtkinter.CTkFrame(self, fg_color="black", corner_radius=5)
        self.id_main_frame.pack(pady=5, padx=20, fill="x")
        self.id_main_frame.pack_propagate(False)

        id_header_frame = customtkinter.CTkFrame(self.id_main_frame, fg_color="transparent")
        id_header_frame.pack(fill="x", padx=10, pady=(3, 0))

        customtkinter.CTkLabel(
            id_header_frame, text="IDs to replace:", text_color=header_text, font=("Arial", 14, "bold")
        ).pack(side="left")

        add_id_button = customtkinter.CTkButton(
            id_header_frame,
            text="Add ID",
            command=self.add_id_entry,
            fg_color=button_color,
            hover_color=button_hover,
            width=70,
            height=20,
            font=header_font
        )
        add_id_button.pack(side="right")

        self.id_entries_frame = customtkinter.CTkScrollableFrame(
            self.id_main_frame, height=80, fg_color="transparent"
        )
        self.id_entries_frame.pack(pady=3, fill="x", padx=10)
        self.add_id_entry()

        output_frame = customtkinter.CTkFrame(self, fg_color="black", corner_radius=5)
        output_frame.pack(pady=5, padx=20, fill="x")

        customtkinter.CTkLabel(
            output_frame, text="Output Folder:", text_color=header_text, font=("Arial", 14, "bold")
        ).pack(anchor="w", padx=10, pady=(3, 0))

        top_output = customtkinter.CTkFrame(output_frame, fg_color="transparent")
        top_output.pack(fill="x", padx=10, pady=3)

        self.output_button = customtkinter.CTkButton(
            top_output,
            text="Select Output Folder",
            command=self.select_output_folder,
            fg_color=button_color,
            hover_color=button_hover,
            height=25,
            font=header_font
        )
        self.output_button.pack(side="left", padx=(0, 10))

        self.output_label = customtkinter.CTkLabel(
            top_output,
            text="No output folder selected",
            justify="left",
            text_color=header_text,
            font=header_font
        )
        self.output_label.pack(side="left", expand=True, fill="x")

        button_frame = customtkinter.CTkFrame(self, fg_color="black", corner_radius=5, height=55)
        button_frame.pack(pady=10, padx=20, fill="x")
        button_frame.pack_propagate(False) 

        self.repack_button = customtkinter.CTkButton(
            button_frame,
            text="Repack Files",
            command=self.repack_files,
            fg_color=button_color,
            hover_color=button_hover,
            height=35,
            font=header_font
        )
        self.repack_button.pack(side="left", expand=True, fill="x", padx=(10, 5))

        self.patch_banks_button = customtkinter.CTkButton(
            button_frame,
            text="Patch Banks/Loop-Points",
            command=self.patch_banks,
            fg_color="#4caf50",
            hover_color="#388e3c",
            text_color_disabled = "#bdbdbd",
            height=35,
            font=header_font
        )
        self.patch_banks_button.pack(side="left", expand=True, fill="x", padx=(5, 10))

        self.patch_banks_textbox = customtkinter.CTkTextbox(
            self,
            width=560,
            height=200,
            fg_color="black",
            text_color="#ffffff",
            corner_radius=5,
            state="disabled",
            font=header_font
        )
        self.patch_banks_textbox.pack(fill="both", expand=False, padx=20, pady=(0, 10))
        set_logger_widget(self.patch_banks_textbox)


    def add_id_entry(self):
        frame = customtkinter.CTkFrame(self.id_entries_frame)
        frame.pack(fill="x", pady=1, padx=5)

        entry = customtkinter.CTkEntry(frame, width=300, height=25)
        entry.pack(side="left", expand=True, fill="x", padx=(0, 5))
        
        remove_button = customtkinter.CTkButton(
            frame,
            text="X",
            command=lambda: self.remove_id_entry(frame, entry),
            fg_color="#6e0000",
            hover_color="#4d0000",
            width=30,
            height=20,
        )
        remove_button.pack(side="right")

        self.id_entries.append(entry)


    def remove_id_entry(self, frame, entry):
        self.id_entries.remove(entry)
        frame.destroy()


    def select_pck_files(self):
        files = filedialog.askopenfilenames(
            title="Select .pck files",
            filetypes=[("PCK files", "*.pck")]
        )
        if files:
            self.pck_files = list(files)
            self.pck_label.configure(text=f"Selected .pck files: {len(self.pck_files)}")
        else:
            self.pck_files = []
            self.pck_label.configure(text="No .pck files selected")


    def select_banks_folder(self):
        folder = filedialog.askdirectory(title="Select Banks Folder")
        if folder:
            self.banks_path = folder
            self.banks_label.configure(text=f"Banks folder: {os.path.basename(folder)}")
        else:
            self.banks_path = ""
            self.banks_label.configure(text="No Banks folder selected")


    def select_wem_file(self):
        file = filedialog.askopenfilename(
            title="Select .wem file",
            filetypes=[("WEM files", "*.wem")]
        )
        if file:
            self.wem_file = file
            self.wem_label.configure(text=f"Selected .wem file: {os.path.basename(file)}")
        else:
            self.wem_file = ""
            self.wem_label.configure(text="No .wem file selected")


    def select_output_folder(self):
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_folder = folder
            self.output_label.configure(text=f"Output folder: {os.path.basename(folder)}")
        else:
            self.output_folder = ""
            self.output_label.configure(text="No output folder selected")


    def repack_files(self):
        if not self.pck_files:
            messagebox.showerror("Error", "Please select at least one .pck file")
            log("Error: Please select at least one .pck file")
            return
        
        pck_name_pattern = re.compile(r'^Music\d+\.pck$')
        for pck_path in self.pck_files:
            pck_name = os.path.basename(pck_path)
            if not pck_name_pattern.match(pck_name):
                messagebox.showerror("Error", f"Invalid .pck file name: {pck_name}. "
                                             "File names must be in the format 'Music[number].pck', e.g., Music0.pck")
                log(f"Invalid .pck file name: {pck_name}. "
                                             "File names must be in the format 'Music[number].pck', e.g., Music0.pck")
                return

        if not self.wem_file:
            messagebox.showerror("Error", "Please select a .wem file")
            log("Error: Please select a .wem file")
            return
        
        self.numeric_ids = []
        for entry in self.id_entries:
            id_val = entry.get().strip()
            if id_val:
                try:
                    if len(id_val) == 16:
                        converted_id = int(id_val, 16)
                    else:
                        converted_id = int(id_val)
                    self.numeric_ids.append(converted_id)
                except ValueError:
                    messagebox.showerror("Error", f"Invalid ID: '{id_val}'. All IDs must be valid integers or 16-character hex strings")
                    log(f"Invalid ID: '{id_val}'. All IDs must be valid integers or 16-character hex strings")
                    return

        if not self.numeric_ids:
            messagebox.showerror("Error", "Please enter at least one numeric ID")
            log("Please enter at least one numeric ID")
            return

        if self.output_folder:
            output_dir = self.output_folder
        else:
            output_dir = os.path.join(os.path.dirname(__file__), "output_pck")
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                log(f"Info: No output folder selected. Using default: {output_dir}")
        log("Info: Starting Repacking...")
        
        wem_data = None
        try:
            with open(self.wem_file, 'rb') as wem_stream:
                wem_data = wem_stream.read()
        except FileNotFoundError:
            messagebox.showerror("Error", "Selected .wem file not found")
            log("Error: Selected .wem file not found")
            return

        pck_count = len(self.pck_files)
        for i, pck_path in enumerate(self.pck_files):
            try:
                modified_pck_package = Package()
                with open(pck_path, 'rb') as pck_stream:
                    modified_pck_package.addfile(BufferedReader(BytesIO(pck_stream.read())))

                replaced_count = 0
                mode = 1
                lang_id = 0
                hash_map = modified_pck_package.map[mode]
                lang_map = hash_map.get(lang_id)

                for numeric_id in self.numeric_ids:
                    if numeric_id in lang_map:
                        new_wem_buffer = BufferedReader(BytesIO(wem_data))
                        modified_pck_package.add_wem(mode, lang_id, numeric_id, new_wem_buffer)
                        log(f"Info: Replaced WEM with ID {numeric_id}")
                        replaced_count += 1
                    else:
                        log(f"Info: ID {numeric_id} not found in {os.path.basename(pck_path)}, skipped")

                if replaced_count > 0:
                    output_pck_path = os.path.join(output_dir, os.path.basename(pck_path))
                    with open(output_pck_path, 'wb') as output_stream:
                        build_pck_file(modified_pck_package, output_stream, modified_pck_package.LANGUAGE_DEF)
                    log(f"Info: Repacked {os.path.basename(pck_path)} ({i + 1}/{pck_count})")
                else:
                    log(f"Info: No IDs were replaced in {os.path.basename(pck_path)}. Skipping save")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to process {os.path.basename(pck_path)}: {e}")
                log(f"Error: Failed to process {os.path.basename(pck_path)}: {e}")
                continue
        log("Info: Repacking complete! You can now Patch the Banks files")

    def patch_banks(self):
        self.numeric_ids = []
        for entry in self.id_entries:
            id_val = entry.get().strip()
            if id_val:
                try:
                    if len(id_val) == 16:
                        converted_id = int(id_val, 16)
                    else:
                        converted_id = int(id_val)
                    self.numeric_ids.append(converted_id)
                except ValueError:
                    messagebox.showerror("Error", f"Invalid ID: '{id_val}'. All IDs must be valid integers or 16-character hex strings")
                    log(f"Invalid ID: '{id_val}'. All IDs must be valid integers or 16-character hex strings")
                    return
    
        if not self.numeric_ids:
            messagebox.showerror("Error", "Please process files first to get a list of IDs")
            log("Error: Please process files first to get a list of IDs")
            return

        if not os.path.exists(self.banks_path):
            messagebox.showerror("Error", f"Banks folder not found at: {self.banks_path}")
            log(f"Error: Banks folder not found at: {self.banks_path}")
            return
            
        output_dir = self.output_folder if self.output_folder else os.path.join(os.path.dirname(__file__), "output_pck")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        wem_duration_str = self.wem_duration_entry.get().strip()
        try:
            wem_duration = float(wem_duration_str)
        except ValueError:
            log("Info: Could not determine the WEM file's duration. Using Wem Length")
            wem_duration = get_wem_duration(self.wem_file)
            if wem_duration is None:
                messagebox.showerror("Error", "An error occurred while getting WEM duration")
                return
            log(f"Info: Wem Length = {wem_duration}")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred while getting WEM duration: {e}")
            log(f"Error: An error occurred while getting WEM duration: {e}")
            return

        found_ids = set()
        not_found_ids = set(self.numeric_ids)
        files_with_couples = []
        
        log("Info: Starting Banks patching...")
        
        banks_files = [f for f in os.scandir(self.banks_path) if re.match(r'Banks\d+\.pck$', f.name)]

        if not banks_files:
            log("Info: No BanksX.pck files found to patch")
            return
        
        banks_file_paths = [f.path for f in banks_files]

        with concurrent.futures.ProcessPoolExecutor() as executor:
            results = executor.map(process_single_bank_file, 
                                   banks_file_paths,
                                   [self.numeric_ids] * len(banks_file_paths))
            
            for bank_file_path, offsets_dict in results:
                if offsets_dict:
                    file_name = os.path.basename(bank_file_path)
                    files_with_couples.append(file_name)
                    
                    output_file_path = os.path.join(output_dir, file_name)
                    patch_bank_file(bank_file_path, output_file_path, offsets_dict, wem_duration)
                    
                    for id_val, offsets in offsets_dict.items():
                        found_ids.add(id_val)
                        if id_val in not_found_ids:
                            not_found_ids.remove(id_val)

        result_text = "Info: Patching complete.\n\n"
        if found_ids:
            result_text += "✅ Found and patched IDs:\n"
            result_text += ", ".join(map(str, sorted(found_ids)))
        
        if files_with_couples:
            result_text += "\n\n📁 Files patched:\n"
            result_text += "\n".join(files_with_couples)

        if not not_found_ids:
            result_text += "\n\n✅ All selected IDs were patched"
        else:
            result_text += "\n\n❌ IDs not found or patched:\n"
            result_text += ", ".join(map(str, sorted(not_found_ids)))
        
        if not found_ids and not not_found_ids:
            result_text = "No IDs were found"
            
        log(result_text)

if __name__ == "__main__":
    app = App()
    app.mainloop()