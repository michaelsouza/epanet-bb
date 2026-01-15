import subprocess
import json

def get_hardware_info():
    """
    Gathers hardware information using shell commands and returns it as a JSON string.
    """
    try:
        # Get CPU info
        cpu_info = subprocess.check_output(['lscpu'], text=True)
        cpu_info = dict(line.split(':', 1) for line in cpu_info.splitlines() if ':' in line)

        # Get Memory info
        mem_info = subprocess.check_output(['free', '-h'], text=True)
        mem_lines = mem_info.splitlines()
        mem_header = mem_lines[0].split()
        mem_values = mem_lines[1].split()
        mem_info = dict(zip(mem_header, mem_values))

        # Get GPU info (if available)
        try:
            gpu_info = subprocess.check_output(['nvidia-smi', '--query-gpu=gpu_name,memory.total', '--format=csv,noheader,nounits'], text=True)
            gpu_info = [line.split(',') for line in gpu_info.splitlines()]
            gpu_info = [{'name': name.strip(), 'memory': mem.strip()} for name, mem in gpu_info]
        except (subprocess.CalledProcessError, FileNotFoundError):
            gpu_info = "N/A"

        # Get OS info
        os_info = subprocess.check_output(['lsb_release', '-d'], text=True).split(":")[-1].strip()

        # Combine all info
        hardware_info = {
            'os': os_info,
            'cpu': cpu_info,
            'memory': mem_info,
            'gpu': gpu_info
        }
        return json.dumps(hardware_info, indent=4)
    except Exception as e:
        return json.dumps({'error': str(e)}, indent=4)

if __name__ == '__main__':
    hardware_data = get_hardware_info()
    print(hardware_data)