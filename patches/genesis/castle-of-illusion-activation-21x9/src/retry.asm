; Castle of Illusion early object activation: bounded retry of a section load whose object allocation failed (pool full), plus the left deletion limit. GAMEPLAY-CHANGING.
; Hooks (each a 6-byte absolute jump patched over the original instructions it replaces, which the hook re-executes or replaces exactly; see the README for the register/flag argument):
;   entry_hook (section loader entry)   : records (column,row) of the call in progress, then the displaced MOVEM d2/d5/d7/a2 (as four pushes, same memory order) and MOVEQ #0,d3
;   fail_hook  (pool scan exhausted)    : the displaced DBF/BRA; queues the section (4 slots, deduplicated by column+row) unless a retry is running or the state key is invalid
;   frame_hook (streamer, after the vertical loader's caller setup): arms the state if its key is wrong, runs the displaced LEA/BSR, then retries every queued section once per streamer invocation
;   level_reset (the single call of the level initialization): clears the whole state and arms the key BEFORE the original level initialization runs
;   left_cull  (object off-screen test at 0x1b12): replaces the unsigned CMPI/BCC window test [0,0x280) by a signed one [-(left lookahead+0x100), right limit); the original unsigned test deleted every object left of the camera. A dead slot (type word 0) of a stale draw list is still deleted when left of the camera, as the original did
; State (work RAM, 48 bytes at 0xfffc00, never written by the original game): +0 col.w +2 row.w of the loader call in progress, +8 fail.b, +9 retrying.b, +0xe key.w 0x5ac3,
; slots at +0x10, 8 bytes each: col.w row.w age.w pad.w (age = streamer invocations left; 0 = empty). The section list pointer is not queued: it depends only on the level layout and is rebuilt as the original does.
free usa-europe 0x00060c80 0x00000400 0xff
org usa-europe 0x00060c80
entry_hook:
  move.w d2,0xfffc00
  move.w d5,0xfffc02
  move.l a2,-(sp)
  move.l d7,-(sp)
  move.l d5,-(sp)
  move.l d2,-(sp)
  moveq #0,d3
  jmp @section_load_body
org usa-europe 0x00060cc0
fail_hook:
  dbra d6,again
  cmpi.w #0x5ac3,0xfffc0e
  bne.s mark
  tst.b 0xfffc09
  bne.s mark
  move.l d0,-(sp)
  move.l d1,-(sp)
  move.l a0,-(sp)
  lea 0xfffc10,a0
  moveq #3,d0
dup1:
  tst.w 4(a0)
  beq.s dup2
  move.w 0xfffc00,d1
  cmp.w (a0),d1
  bne.s dup2
  move.w 0xfffc02,d1
  cmp.w 2(a0),d1
  bne.s dup2
  bra.s done
dup2:
  lea 8(a0),a0
  dbra d0,dup1
  lea 0xfffc10,a0
  moveq #3,d0
emp1:
  tst.w 4(a0)
  bne.s emp2
  move.w 0xfffc00,(a0)
  move.w 0xfffc02,2(a0)
  move.w #24,4(a0)
  bra.s done
emp2:
  lea 8(a0),a0
  dbra d0,emp1
done:
  movea.l (sp)+,a0
  move.l (sp)+,d1
  move.l (sp)+,d0
mark:
  move.b #1,0xfffc08
  tst.w -0x40(a3)
  jmp @next_entry
again:
  jmp @slot_scan
org usa-europe 0x00060e00
frame_hook:
  cmpi.w #0x5ac3,0xfffc0e
  beq.s keyok0
  clr.l 0xfffc00
  clr.l 0xfffc04
  clr.l 0xfffc08
  clr.l 0xfffc0c
  clr.l 0xfffc10
  clr.l 0xfffc14
  clr.l 0xfffc18
  clr.l 0xfffc1c
  clr.l 0xfffc20
  clr.l 0xfffc24
  clr.l 0xfffc28
  clr.l 0xfffc2c
  move.w #0x5ac3,0xfffc0e
keyok0:
  lea 0xfffffa80,a6
  jsr @vertical_loader
  move.l d0,-(sp)
  move.l d1,-(sp)
  move.l d2,-(sp)
  move.l d3,-(sp)
  move.l d4,-(sp)
  move.l d5,-(sp)
  move.l d6,-(sp)
  move.l d7,-(sp)
  move.l a0,-(sp)
  move.l a1,-(sp)
  move.l a2,-(sp)
  move.l a3,-(sp)
  move.l a4,-(sp)
  move.l a5,-(sp)
  move.l a6,-(sp)
  lea 0xfffc10,a0
  moveq #3,d0
slot:
  tst.w 4(a0)
  beq next
  move.w 4(a0),d1
  dbra d1,age1
age1:
  move.w d1,4(a0)
  move.w (a0),d1
  movea.w (a0),a1
  lea 0x81(a1),a1
  move.w a1,d1
  movea.w 0xfffa84,a1
  lea 0x3f00(a1),a1
  move.w a1,d2
  ror.w #7,d2
  andi.w #0x1ff,d2
  cmp.w d2,d1
  blt inval
  movea.w (a0),a1
  lea 0x7f(a1),a1
  move.w a1,d1
  movea.w 0xfffa84,a1
  lea 0x4280(a1),a1
  move.w a1,d2
  ror.w #7,d2
  andi.w #0x1ff,d2
  cmp.w d2,d1
  bgt inval
  movea.w 0xfffa80,a1
  lea 0x4000(a1),a1
  move.w a1,d2
  ror.w #7,d2
  andi.w #0x1ff,d2
  movea.w 2(a0),a1
  lea 0x82(a1),a1
  move.w a1,d1
  cmp.w d2,d1
  blt inval
  movea.w 2(a0),a1
  lea 0x7b(a1),a1
  move.w a1,d1
  cmp.w d2,d1
  bgt inval
  move.l a0,-(sp)
  move.l d0,-(sp)
  clr.b 0xfffc08
  move.b #1,0xfffc09
  move.w (a0),d2
  move.w 2(a0),d5
  lea 0xffffca02,a1
  movea.w 0xffca00,a2
  lea -0x3600(a2),a2
  jsr @section_load
  clr.b 0xfffc09
  move.l (sp)+,d0
  movea.l (sp)+,a0
  tst.b 0xfffc08
  bne.s still
  clr.w 4(a0)
  bra.s next
still:
  tst.w 4(a0)
  bne.s next
  bra.s next
inval:
  clr.w 4(a0)
next:
  lea 8(a0),a0
  dbra d0,slot
  movea.l (sp)+,a6
  movea.l (sp)+,a5
  movea.l (sp)+,a4
  movea.l (sp)+,a3
  movea.l (sp)+,a2
  movea.l (sp)+,a1
  movea.l (sp)+,a0
  move.l (sp)+,d7
  move.l (sp)+,d6
  move.l (sp)+,d5
  move.l (sp)+,d4
  move.l (sp)+,d3
  move.l (sp)+,d2
  move.l (sp)+,d1
  move.l (sp)+,d0
  jmp @streamer_tail
org usa-europe 0x00061000
level_reset:
  clr.l 0xfffc00
  clr.l 0xfffc04
  clr.l 0xfffc08
  clr.l 0xfffc0c
  clr.l 0xfffc10
  clr.l 0xfffc14
  clr.l 0xfffc18
  clr.l 0xfffc1c
  clr.l 0xfffc20
  clr.l 0xfffc24
  clr.l 0xfffc28
  clr.l 0xfffc2c
  move.w #0x5ac3,0xfffc0e
  jmp @level_init
org usa-europe 0x00061060
left_cull:
  cmpi.w #-0x200,d4
  blt.s cull_it
  cmpi.w #0x380,d4
  bge.s cull_it
  tst.w d4
  bpl.s keep
  tst.w (a0)
  beq.s cull_it
keep:
  jmp @cull_continue
cull_it:
  jmp @cull_delete
