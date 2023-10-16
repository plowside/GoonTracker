z={
'TEST':'wl4ie7urftg'
}
import os

for x in z:
	#os.system(f'setx {x} {z[x]}')
	#os.environ[x] = z[x]
	print(f'{x} = {os.getenv(x)}')


