import paramiko, sys
HOST='192.168.192.5'; USER='AAAA'; PW='1111'

def connect():
    c=paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PW, timeout=8, look_for_keys=False, allow_agent=False)
    return c

def run(c, cmd, timeout=30, get_pty=False):
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout, get_pty=get_pty)
    out=stdout.read().decode(errors='replace'); err=stderr.read().decode(errors='replace')
    return out, err

if __name__=='__main__':
    c=connect()
    for cmd in ['whoami','id','uname -a','hostname -I','cat /etc/os-release | head -2']:
        o,e=run(c,cmd)
        print(f'$ {cmd}\n{o.strip()}{("  [err] "+e.strip()) if e.strip() else ""}\n')
    c.close()
