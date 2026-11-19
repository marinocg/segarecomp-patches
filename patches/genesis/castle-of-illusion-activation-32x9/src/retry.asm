; Castle of Illusion 32:9 object activation: wider section lookaheads, bounded retry of a section load whose allocation failed (pool full), DEFERRAL of speculative sections while the layout pool is nearly full, and the left deletion limit. GAMEPLAY-CHANGING.
; Hooks (each a 6-byte absolute jump patched over the original instructions it replaces, which the hook re-executes or replaces exactly):
;   entry_hook (section loader entry)  : records (column,row); DEFERS the section (queue it and return, exactly as the loader would after loading nothing) when the layout pool (0xD400..0xDBFF, 32 slots) holds at least 20 objects AND the column lies beyond the ORIGINAL game's window
;                                         (right of (camera+0x180)>>7, or left of (camera-0xF1)>>7); otherwise the displaced MOVEM d2/d5/d7/a2 (as four pushes) and MOVEQ #0,d3
;   fail_hook  (pool scan exhausted)   : queues the section (16 slots, deduplicated by column+row) unless a retry is running or the state key is invalid
;   frame_hook (streamer)              : arms the state, runs the displaced LEA/BSR, retries every queued section once per streamer invocation; a section deferred again in a retry keeps its age (it is waiting, not failing)
;   level_reset                        : clears the state BEFORE the original level initialization
;   left_cull (0x1b12)                 : signed window test [-(left lookahead+0x100), right limit) instead of the unsigned [0,0x280); dead slots of a stale draw list are still deleted
; Deferral reads only guest state (camera word 0xFA84 and the pool), never host presentation. A deferred section is revisited by the retry ring; it is dropped (as the original would never have loaded it) once it leaves the retry window, and the game's own streamer asks for it again on re-entry.
; State (work RAM, never written by the original game): 0xfffc00..0xfffc8f: +0 col.w +2 row.w of the call in progress, +8 fail.b, +9 retrying.b, +0xa deferred-in-retry.b, +0xe key.w 0x5ac3, 16 slots at +0x10 (8 bytes: col.w row.w age.w pad.w; age 0 = empty);
; diagnostics only (never read by the game): 0xfffca0 fail events, +2 retry successes, +4 expired, +6 ring-full drops, +8 deferral attempts, +0xa deferred retries kept waiting (each a word).
free usa-europe 0x00060c80 0x00000600 0xff
org usa-europe 0x00060c80
entry_hook:
  move.w d2,0xfffc00
  move.w d5,0xfffc02
  cmpi.w #0x5ac3,0xfffc0e
  bne.s nodefer
  lea 0xffffd400,a3
  moveq #31,d6
  moveq #0,d3
dcnt:
  tst.w (a3)
  beq.s dcz
  addq.w #1,d3
dcz:
  lea 0x40(a3),a3
  dbra d6,dcnt
  cmpi.w #20,d3
  blt.s nodefer
  move.w 0xfffa84,d3
  addi.w #0x180,d3
  asr.w #7,d3
  cmp.w d3,d2
  bgt.s dodefer
  move.w 0xfffa84,d3
  subi.w #0xf1,d3
  bmi.s nodefer
  asr.w #7,d3
  cmp.w d3,d2
  bge.s nodefer
dodefer:
  jmp defer_sec
nodefer:
  move.l a2,-(sp)
  move.l d7,-(sp)
  move.l d5,-(sp)
  move.l d2,-(sp)
  moveq #0,d3
  jmp @section_load_body
org usa-europe 0x00060d40
fail_hook:
  dbra d6,again
  addq.w #1,0xfffca0
  cmpi.w #0x5ac3,0xfffc0e
  bne.s mark
  tst.b 0xfffc09
  bne.s mark
  move.l d0,-(sp)
  move.l d1,-(sp)
  move.l a0,-(sp)
  lea 0xfffc10,a0
  moveq #15,d0
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
  moveq #15,d0
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
  addq.w #1,0xfffca6
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
  move.l a0,-(sp)
  move.l d0,-(sp)
  lea 0xfffc00,a0
  moveq #35,d0
clrf:
  clr.l (a0)+
  dbra d0,clrf
  move.l (sp)+,d0
  movea.l (sp)+,a0
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
  moveq #15,d0
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
  lea 0x3e80(a1),a1
  move.w a1,d2
  ror.w #7,d2
  andi.w #0x1ff,d2
  cmp.w d2,d1
  blt inval
  movea.w (a0),a1
  lea 0x7f(a1),a1
  move.w a1,d1
  movea.w 0xfffa84,a1
  lea 0x42c0(a1),a1
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
  clr.b 0xfffc0a
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
  addq.w #1,0xfffca2
  clr.w 4(a0)
  bra.s next
still:
  tst.b 0xfffc0a
  beq.s nodef
  clr.b 0xfffc0a
  addq.w #1,4(a0)
  addq.w #1,0xfffcaa
  bra.s next
nodef:
  tst.w 4(a0)
  bne.s next
  addq.w #1,0xfffca4
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
  move.l a0,-(sp)
  move.l d0,-(sp)
  lea 0xfffc00,a0
  moveq #35,d0
clrr:
  clr.l (a0)+
  dbra d0,clrr
  move.l (sp)+,d0
  movea.l (sp)+,a0
  move.w #0x5ac3,0xfffc0e
  jmp @level_init
org usa-europe 0x00061060
left_cull:
  cmpi.w #-0x280,d4
  blt.s cull_it
  cmpi.w #0x3c0,d4
  bge.s cull_it
  tst.w d4
  bpl.s keep
  tst.w (a0)
  beq.s cull_it
keep:
  jmp @cull_continue
cull_it:
  jmp @cull_delete
org usa-europe 0x00061100
defer_sec:
  tst.b 0xfffc09
  beq.s dq
  move.b #1,0xfffc08
  move.b #1,0xfffc0a
  rts
dq:
  move.l d0,-(sp)
  move.l d1,-(sp)
  move.l a0,-(sp)
  lea 0xfffc10,a0
  moveq #15,d0
ddup1:
  tst.w 4(a0)
  beq.s ddup2
  move.w 0xfffc00,d1
  cmp.w (a0),d1
  bne.s ddup2
  move.w 0xfffc02,d1
  cmp.w 2(a0),d1
  bne.s ddup2
  bra.s ddone
ddup2:
  lea 8(a0),a0
  dbra d0,ddup1
  lea 0xfffc10,a0
  moveq #15,d0
demp1:
  tst.w 4(a0)
  bne.s demp2
  move.w 0xfffc00,(a0)
  move.w 0xfffc02,2(a0)
  move.w #24,4(a0)
  bra.s ddone
demp2:
  lea 8(a0),a0
  dbra d0,demp1
  addq.w #1,0xfffca6
ddone:
  addq.w #1,0xfffca8
  movea.l (sp)+,a0
  move.l (sp)+,d1
  move.l (sp)+,d0
  rts
