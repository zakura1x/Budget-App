"""
app/db/repositories - THE ONLY LAYER BESIDES app/core/crypto/ THAT SEES A
CIPHERTEXT. Repositories hand services decrypted records and accept plaintext
back; a service author never has to remember to encrypt anything.
"""
