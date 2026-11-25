FaxSend - send faxes by saving a PDF into a folder
==================================================

SETUP (one time)
1. Right-click the zip file and choose "Extract All...".
   (Do not run FaxSend.exe from inside the zip.)
2. Open the extracted folder and double-click FaxSend.exe.
3. Click "Yes" when Windows asks for permission.
   If Windows shows "Windows protected your PC", click "More info" then "Run anyway".
4. Wait for the message "FaxSend is installed and running in the background",
   then press Enter. You can delete the zip and the extracted folder afterwards.

FaxSend now runs by itself in the background and starts with Windows.
There is nothing to open or keep running. A copy of this file is saved in
Documents\FaxSend\README.txt.

SENDING A FAX
Save or copy a PDF into:   Documents\FaxSend\Outbox
Name the file with the 10 digit fax number, for example:
    4165551234.pdf
    4165551234 lab results.pdf      (text after the number is fine)

Within a few seconds the file moves to:
    Documents\FaxSend\Sent      - the fax was handed to the fax server
    Documents\FaxSend\Failed    - there was a problem (see below)

If the PDF is still open (for example in Adobe), FaxSend waits and sends it
as soon as you close it. Faxes being sent appear briefly in Outbox\Sending.

If the internet or phone system is down, faxes wait in the Outbox and go out
automatically when the connection is back.

HISTORY
Documents\FaxSend\Logs\log.txt lists every fax with date, time, number and result.

CHECKING THAT IT IS RUNNING
Double-click FaxSend.exe (in C:\Program Files\FaxSend) to see its status and
the last faxes sent.

PROBLEMS
A file in the Failed folder means it was not sent. Check the number in the file
name and the reason in log.txt, then move the file back into the Outbox to try
again. If it keeps failing, contact your phone system provider.

UNINSTALLING
1. Press the Windows key, type cmd, and press Enter to open a Command Prompt.
2. Type this command (with the quotes) and press Enter:
       "C:\Program Files\FaxSend\FaxSend.exe" --uninstall
3. Click "Yes" when Windows asks for permission, then press Enter when it
   says the background task was removed.
4. Delete the folder C:\Program Files\FaxSend.
5. Your faxes are still in Documents\FaxSend (Outbox, Sent, Failed, Logs).
   They may contain patient information - keep them or delete the folder
   according to your clinic's records policy.

To check the status from a Command Prompt instead of double-clicking:
       "C:\Program Files\FaxSend\FaxSend.exe" --status
