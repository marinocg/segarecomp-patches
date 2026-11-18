; Castle of Illusion early object activation: bounded retry of a section load whose object allocation failed (pool full). GAMEPLAY-CHANGING.
; State (work RAM, 48 bytes at 0xfffc00, never written by the original game): +0 col.w +2 row.w of the loader call in progress, +8 fail.b, +9 retrying.b, +0xe key.w 0x5ac3,
; slots at +0x10, 8 bytes each: col.w row.w age.w pad.w (age = streamer invocations left; 0 = empty). The section list pointer is not queued: it is a function of the level layout and is rebuilt like the original does.
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
  jmp @next_entry
again:
  jmp @slot_scan
org usa-europe 0x00060e00
frame_hook:
  lea 0xfffa80,a6
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
  cmpi.w #0x5ac3,0xfffc0e
  beq.s keyok
  lea 0xfffc00,a0
  moveq #11,d0
clr1:
  clr.l (a0)+
  dbra d0,clr1
  move.w #0x5ac3,0xfffc0e
keyok:
  lea 0xfffc10,a0
  moveq #3,d0
slot:
  tst.w 4(a0)
  beq next
  subq.w #1,4(a0)
  move.w (a0),d1
  move.w 0xfffa84,d2
  lsr.w #7,d2
  subq.w #1,d2
  cmp.w d2,d1
  blt inval
  move.w 0xfffa84,d2
  addi.w #0x280,d2
  lsr.w #7,d2
  addq.w #1,d2
  cmp.w d2,d1
  bgt inval
  move.w 2(a0),d1
  move.w 0xfffa80,d2
  lsr.w #7,d2
  subq.w #2,d2
  cmp.w d2,d1
  blt inval
  addq.w #7,d2
  cmp.w d2,d1
  bgt inval
  move.l a0,-(sp)
  move.l d0,-(sp)
  clr.b 0xfffc08
  move.b #1,0xfffc09
  move.w (a0),d2
  move.w 2(a0),d5
  lea 0xffffca02,a1
  move.w 0xffca00,d3
  ext.l d3
  addi.l #0xffffca00,d3
  movea.l d3,a2
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
