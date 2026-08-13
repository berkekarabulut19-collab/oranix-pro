
 = New-Object -ComObject WScript.Shell
 = .CreateShortcut('C:\Users\Berke\Desktop\ORANİX PRO.lnk')
.TargetPath = 'C:\Users\Berke\Desktop\IddaaTahminPro\dist\OranixPro\OranixPro.exe'
.WorkingDirectory = 'C:\Users\Berke\Desktop\IddaaTahminPro\dist\OranixPro'
.IconLocation = 'C:\Users\Berke\Desktop\IddaaTahminPro\dist\OranixPro\OranixPro.exe,0'
.Save()
