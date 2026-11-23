//=====================================================================
//
// KCP - A Better ARQ Protocol Implementation
// skywind3000 (at) gmail.com, 2011-2017
//
//=====================================================================
#include "ikcp.h"
#include <stdarg.h>
#include <stdio.h>

#define IQUEUE_INIT(head) do { \
    (head)->next = (head); (head)->prev = (head); \
} while (0)

#define IQUEUE_EMPTY(head) ((head)->next == (head))

#define IQUEUE_ADD(node, head) do { \
    (node)->next = (head)->next; (node)->prev = (head); \
    (head)->next->prev = (node); (head)->next = (node); \
} while (0)

#define IQUEUE_ADD_TAIL(node, head) do { \
    (node)->prev = (head)->prev; (node)->next = (head); \
    (head)->prev->next = (node); (head)->prev = (node); \
} while (0)

#define IQUEUE_DEL(entry) do { \
    (entry)->next->prev = (entry)->prev; \
    (entry)->prev->next = (entry)->next; \
    (entry)->next = 0; (entry)->prev = 0; \
} while (0)

#define IQUEUE_ENTRY(ptr, type, member) \
    ((type*)((char*)(ptr) - (size_t)(&((type*)0)->member)))

struct IKCPSEG {
    struct IQUEUEHEAD node;
    IUINT32 conv;
    IUINT32 cmd;
    IUINT32 frg;
    IUINT32 wnd;
    IUINT32 ts;
    IUINT32 sn;
    IUINT32 una;
    IUINT32 len;
    IUINT32 resendts;
    IUINT32 rto;
    IUINT32 fastack;
    IUINT32 xmit;
    char data[1];
};

static inline void* ikcp_malloc(size_t size) { return malloc(size); }
static inline void ikcp_free(void *ptr) { free(ptr); }

static inline IUINT32 _imin_(IUINT32 a, IUINT32 b) { return a <= b ? a : b; }
static inline IUINT32 _imax_(IUINT32 a, IUINT32 b) { return a >= b ? a : b; }
static inline IUINT32 _ibound_(IUINT32 lower, IUINT32 middle, IUINT32 upper) {
    return _imin_(_imax_(lower, middle), upper);
}
static inline long _itimediff(IUINT32 later, IUINT32 earlier) {
    return ((long)(later - earlier));
}

static struct IKCPSEG* ikcp_segment_new(ikcpcb *kcp, int size) {
    (void)kcp;
    return (struct IKCPSEG*)ikcp_malloc(sizeof(struct IKCPSEG) + size);
}

static void ikcp_segment_delete(ikcpcb *kcp, struct IKCPSEG *seg) {
    (void)kcp;
    ikcp_free(seg);
}

static inline void ikcp_encode32u(char *p, IUINT32 l) {
    *(unsigned char*)(p + 0) = (unsigned char)((l >>  0) & 0xff);
    *(unsigned char*)(p + 1) = (unsigned char)((l >>  8) & 0xff);
    *(unsigned char*)(p + 2) = (unsigned char)((l >> 16) & 0xff);
    *(unsigned char*)(p + 3) = (unsigned char)((l >> 24) & 0xff);
}

static inline void ikcp_decode32u(const char *p, IUINT32 *l) {
    *l = (IUINT32)(*(const unsigned char*)(p + 0)) |
        ((IUINT32)(*(const unsigned char*)(p + 1)) <<  8) |
        ((IUINT32)(*(const unsigned char*)(p + 2)) << 16) |
        ((IUINT32)(*(const unsigned char*)(p + 3)) << 24);
}

static inline void ikcp_encode16u(char *p, IUINT16 l) {
    *(unsigned char*)(p + 0) = (unsigned char)((l >> 0) & 0xff);
    *(unsigned char*)(p + 1) = (unsigned char)((l >> 8) & 0xff);
}

static inline void ikcp_decode16u(const char *p, IUINT16 *l) {
    *l = (IUINT16)(*(const unsigned char*)(p + 0)) |
        ((IUINT16)(*(const unsigned char*)(p + 1)) << 8);
}

static inline void ikcp_encode8u(char *p, IUINT8 c) {
    *(unsigned char*)p = (unsigned char)c;
}

static inline void ikcp_decode8u(const char *p, IUINT8 *c) {
    *c = *(const unsigned char*)p;
}

ikcpcb* ikcp_create(IUINT32 conv, void *user) {
    ikcpcb *kcp = (ikcpcb*)ikcp_malloc(sizeof(ikcpcb));
    if (kcp == NULL) return NULL;
    memset(kcp, 0, sizeof(ikcpcb));
    kcp->conv = conv;
    kcp->user = user;
    kcp->snd_una = 0;
    kcp->snd_nxt = 0;
    kcp->rcv_nxt = 0;
    kcp->ts_recent = 0;
    kcp->ts_lastack = 0;
    kcp->ts_probe = 0;
    kcp->probe_wait = 0;
    kcp->snd_wnd = IKCP_WND_SND;
    kcp->rcv_wnd = IKCP_WND_RCV;
    kcp->rmt_wnd = IKCP_WND_RCV;
    kcp->cwnd = 0;
    kcp->incr = 0;
    kcp->probe = 0;
    kcp->mtu = IKCP_MTU_DEF;
    kcp->mss = kcp->mtu - IKCP_OVERHEAD;
    kcp->buffer = (char*)ikcp_malloc((kcp->mtu + IKCP_OVERHEAD) * 3);
    if (kcp->buffer == NULL) {
        ikcp_free(kcp);
        return NULL;
    }
    IQUEUE_INIT(&kcp->snd_queue);
    IQUEUE_INIT(&kcp->rcv_queue);
    IQUEUE_INIT(&kcp->snd_buf);
    IQUEUE_INIT(&kcp->rcv_buf);
    kcp->nrcv_buf = 0;
    kcp->nsnd_buf = 0;
    kcp->nrcv_que = 0;
    kcp->nsnd_que = 0;
    kcp->state = 0;
    kcp->acklist = NULL;
    kcp->ackblock = 0;
    kcp->ackcount = 0;
    kcp->rx_srtt = 0;
    kcp->rx_rttval = 0;
    kcp->rx_rto = IKCP_RTO_DEF;
    kcp->rx_minrto = IKCP_RTO_MIN;
    kcp->current = 0;
    kcp->interval = IKCP_INTERVAL;
    kcp->ts_flush = IKCP_INTERVAL;
    kcp->nodelay = 0;
    kcp->updated = 0;
    kcp->logmask = 0;
    kcp->ssthresh = IKCP_THRESH_INIT;
    kcp->fastresend = 0;
    kcp->fastlimit = IKCP_ACK_FAST;
    kcp->nocwnd = 0;
    kcp->xmit = 0;
    kcp->dead_link = IKCP_DEADLINK;
    kcp->output = NULL;
    kcp->writelog = NULL;
    return kcp;
}

void ikcp_release(ikcpcb *kcp) {
    if (kcp) {
        struct IQUEUEHEAD *p;
        while (!IQUEUE_EMPTY(&kcp->snd_buf)) {
            p = kcp->snd_buf.next;
            IQUEUE_DEL(p);
            ikcp_segment_delete(kcp, IQUEUE_ENTRY(p, struct IKCPSEG, node));
        }
        while (!IQUEUE_EMPTY(&kcp->rcv_buf)) {
            p = kcp->rcv_buf.next;
            IQUEUE_DEL(p);
            ikcp_segment_delete(kcp, IQUEUE_ENTRY(p, struct IKCPSEG, node));
        }
        while (!IQUEUE_EMPTY(&kcp->snd_queue)) {
            p = kcp->snd_queue.next;
            IQUEUE_DEL(p);
            ikcp_segment_delete(kcp, IQUEUE_ENTRY(p, struct IKCPSEG, node));
        }
        while (!IQUEUE_EMPTY(&kcp->rcv_queue)) {
            p = kcp->rcv_queue.next;
            IQUEUE_DEL(p);
            ikcp_segment_delete(kcp, IQUEUE_ENTRY(p, struct IKCPSEG, node));
        }
        if (kcp->buffer) {
            ikcp_free(kcp->buffer);
            kcp->buffer = NULL;
        }
        if (kcp->acklist) {
            ikcp_free(kcp->acklist);
            kcp->acklist = NULL;
        }
        kcp->nrcv_buf = 0;
        kcp->nsnd_buf = 0;
        kcp->nrcv_que = 0;
        kcp->nsnd_que = 0;
        kcp->ackcount = 0;
        kcp->buffer = NULL;
        kcp->acklist = NULL;
        ikcp_free(kcp);
    }
}

void ikcp_setoutput(ikcpcb *kcp, int (*output)(const char *buf, int len, ikcpcb *kcp, void *user)) {
    kcp->output = output;
}

int ikcp_peeksize(const ikcpcb *kcp) {
    struct IQUEUEHEAD *p;
    struct IKCPSEG *seg;
    int length = 0;
    if (IQUEUE_EMPTY(&kcp->rcv_queue)) return -1;
    seg = IQUEUE_ENTRY(kcp->rcv_queue.next, struct IKCPSEG, node);
    if (seg->frg == 0) return seg->len;
    if (kcp->nrcv_que < seg->frg + 1) return -1;
    for (p = kcp->rcv_queue.next; p != &kcp->rcv_queue; p = p->next) {
        seg = IQUEUE_ENTRY(p, struct IKCPSEG, node);
        length += seg->len;
        if (seg->frg == 0) break;
    }
    return length;
}

int ikcp_recv(ikcpcb *kcp, char *buffer, int len) {
    struct IQUEUEHEAD *p;
    int ispeek = (len < 0) ? 1 : 0;
    int peeksize;
    int recover = 0;
    struct IKCPSEG *seg;
    if (IQUEUE_EMPTY(&kcp->rcv_queue)) return -1;
    if (len < 0) len = -len;
    peeksize = ikcp_peeksize(kcp);
    if (peeksize < 0) return -2;
    if (peeksize > len) return -3;
    if (kcp->nrcv_que >= kcp->rcv_wnd) recover = 1;
    for (len = 0, p = kcp->rcv_queue.next; p != &kcp->rcv_queue; ) {
        seg = IQUEUE_ENTRY(p, struct IKCPSEG, node);
        p = p->next;
        if (buffer) {
            memcpy(buffer, seg->data, seg->len);
            buffer += seg->len;
        }
        len += seg->len;
        int fragment = seg->frg;
        if (ispeek == 0) {
            IQUEUE_DEL(&seg->node);
            ikcp_segment_delete(kcp, seg);
            kcp->nrcv_que--;
        }
        if (fragment == 0) break;
    }
    while (!IQUEUE_EMPTY(&kcp->rcv_buf)) {
        seg = IQUEUE_ENTRY(kcp->rcv_buf.next, struct IKCPSEG, node);
        if (seg->sn == kcp->rcv_nxt && kcp->nrcv_que < kcp->rcv_wnd) {
            IQUEUE_DEL(&seg->node);
            kcp->nrcv_buf--;
            IQUEUE_ADD_TAIL(&seg->node, &kcp->rcv_queue);
            kcp->nrcv_que++;
            kcp->rcv_nxt++;
        } else {
            break;
        }
    }
    if (kcp->nrcv_que < kcp->rcv_wnd && recover) {
        kcp->probe |= IKCP_ASK_TELL;
    }
    return len;
}

int ikcp_send(ikcpcb *kcp, const char *buffer, int len) {
    struct IKCPSEG *seg;
    int count, i;
    if (len < 0) return -1;
    if (len <= (int)kcp->mss) count = 1;
    else count = (len + kcp->mss - 1) / kcp->mss;
    if (count >= (int)IKCP_WND_RCV) return -2;
    if (count == 0) count = 1;
    for (i = 0; i < count; i++) {
        int size = len > (int)kcp->mss ? (int)kcp->mss : len;
        seg = ikcp_segment_new(kcp, size);
        if (seg == NULL) return -2;
        if (buffer && len > 0) memcpy(seg->data, buffer, size);
        seg->len = size;
        seg->frg = count - i - 1;
        IQUEUE_INIT(&seg->node);
        IQUEUE_ADD_TAIL(&seg->node, &kcp->snd_queue);
        kcp->nsnd_que++;
        if (buffer) buffer += size;
        len -= size;
    }
    return 0;
}

static void ikcp_update_ack(ikcpcb *kcp, IINT32 rtt) {
    IINT32 rto = 0;
    if (kcp->rx_srtt == 0) {
        kcp->rx_srtt = rtt;
        kcp->rx_rttval = rtt / 2;
    } else {
        long delta = rtt - kcp->rx_srtt;
        if (delta < 0) delta = -delta;
        kcp->rx_rttval = (3 * kcp->rx_rttval + delta) / 4;
        kcp->rx_srtt = (7 * kcp->rx_srtt + rtt) / 8;
        if (kcp->rx_srtt < 1) kcp->rx_srtt = 1;
    }
    rto = kcp->rx_srtt + _imax_(kcp->interval, 4 * kcp->rx_rttval);
    kcp->rx_rto = _ibound_(kcp->rx_minrto, rto, IKCP_RTO_MAX);
}

static void ikcp_shrink_buf(ikcpcb *kcp) {
    struct IQUEUEHEAD *p = kcp->snd_buf.next;
    if (p != &kcp->snd_buf) {
        struct IKCPSEG *seg = IQUEUE_ENTRY(p, struct IKCPSEG, node);
        kcp->snd_una = seg->sn;
    } else {
        kcp->snd_una = kcp->snd_nxt;
    }
}

static void ikcp_parse_ack(ikcpcb *kcp, IUINT32 sn) {
    struct IQUEUEHEAD *p, *next;
    if (_itimediff(sn, kcp->snd_una) < 0 || _itimediff(sn, kcp->snd_nxt) >= 0) return;
    for (p = kcp->snd_buf.next; p != &kcp->snd_buf; p = next) {
        struct IKCPSEG *seg = IQUEUE_ENTRY(p, struct IKCPSEG, node);
        next = p->next;
        if (sn == seg->sn) {
            IQUEUE_DEL(p);
            ikcp_segment_delete(kcp, seg);
            kcp->nsnd_buf--;
            break;
        }
        if (_itimediff(sn, seg->sn) < 0) break;
    }
}

static void ikcp_parse_una(ikcpcb *kcp, IUINT32 una) {
    struct IQUEUEHEAD *p, *next;
    for (p = kcp->snd_buf.next; p != &kcp->snd_buf; p = next) {
        struct IKCPSEG *seg = IQUEUE_ENTRY(p, struct IKCPSEG, node);
        next = p->next;
        if (_itimediff(una, seg->sn) > 0) {
            IQUEUE_DEL(p);
            ikcp_segment_delete(kcp, seg);
            kcp->nsnd_buf--;
        } else {
            break;
        }
    }
}

static void ikcp_parse_fastack(ikcpcb *kcp, IUINT32 sn, IUINT32 ts) {
    struct IQUEUEHEAD *p, *next;
    (void)ts;
    if (_itimediff(sn, kcp->snd_una) < 0 || _itimediff(sn, kcp->snd_nxt) >= 0) return;
    for (p = kcp->snd_buf.next; p != &kcp->snd_buf; p = next) {
        struct IKCPSEG *seg = IQUEUE_ENTRY(p, struct IKCPSEG, node);
        next = p->next;
        if (_itimediff(sn, seg->sn) < 0) break;
        else if (sn != seg->sn) {
            seg->fastack++;
        }
    }
}

static void ikcp_ack_push(ikcpcb *kcp, IUINT32 sn, IUINT32 ts) {
    IUINT32 newsize = kcp->ackcount + 1;
    IUINT32 *ptr;
    if (newsize > kcp->ackblock) {
        IUINT32 newblock = 8;
        while (newblock < newsize) newblock <<= 1;
        ptr = (IUINT32*)ikcp_malloc(newblock * sizeof(IUINT32) * 2);
        if (ptr == NULL) return;
        if (kcp->acklist != NULL) {
            for (IUINT32 x = 0; x < kcp->ackcount; x++) {
                ptr[x * 2 + 0] = kcp->acklist[x * 2 + 0];
                ptr[x * 2 + 1] = kcp->acklist[x * 2 + 1];
            }
            ikcp_free(kcp->acklist);
        }
        kcp->acklist = ptr;
        kcp->ackblock = newblock;
    }
    ptr = &kcp->acklist[kcp->ackcount * 2];
    ptr[0] = sn;
    ptr[1] = ts;
    kcp->ackcount++;
}

static inline int ikcp_wnd_unused(const ikcpcb *kcp) {
    if (kcp->nrcv_que < kcp->rcv_wnd) {
        return (int)(kcp->rcv_wnd - kcp->nrcv_que);
    }
    return 0;
}

static char *ikcp_encode_seg(char *ptr, const struct IKCPSEG *seg) {
    ikcp_encode32u(ptr, seg->conv); ptr += 4;
    ikcp_encode8u(ptr, (IUINT8)seg->cmd); ptr += 1;
    ikcp_encode8u(ptr, (IUINT8)seg->frg); ptr += 1;
    ikcp_encode16u(ptr, (IUINT16)seg->wnd); ptr += 2;
    ikcp_encode32u(ptr, seg->ts); ptr += 4;
    ikcp_encode32u(ptr, seg->sn); ptr += 4;
    ikcp_encode32u(ptr, seg->una); ptr += 4;
    ikcp_encode32u(ptr, seg->len); ptr += 4;
    return ptr;
}

void ikcp_flush(ikcpcb *kcp) {
    IUINT32 current = kcp->current;
    char *buffer = kcp->buffer;
    char *ptr = buffer;
    int count, size, i;
    IUINT32 resent, cwnd;
    struct IKCPSEG seg;
    struct IQUEUEHEAD *p;
    int change = 0;
    int lost = 0;

    if (kcp->updated == 0) return;

    seg.conv = kcp->conv;
    seg.cmd = IKCP_CMD_ACK;
    seg.frg = 0;
    seg.wnd = ikcp_wnd_unused(kcp);
    seg.una = kcp->rcv_nxt;
    seg.len = 0;
    seg.sn = 0;
    seg.ts = 0;

    count = kcp->ackcount;
    for (i = 0; i < count; i++) {
        size = (int)(ptr - buffer);
        if (size + (int)IKCP_OVERHEAD > (int)kcp->mtu) {
            kcp->output(buffer, size, kcp, kcp->user);
            ptr = buffer;
        }
        seg.sn = kcp->acklist[i * 2 + 0];
        seg.ts = kcp->acklist[i * 2 + 1];
        ptr = ikcp_encode_seg(ptr, &seg);
    }
    kcp->ackcount = 0;

    if (kcp->rmt_wnd == 0) {
        if (kcp->probe_wait == 0) {
            kcp->probe_wait = IKCP_PROBE_INIT;
            kcp->ts_probe = kcp->current + kcp->probe_wait;
        } else {
            if (_itimediff(kcp->current, kcp->ts_probe) >= 0) {
                if (kcp->probe_wait < IKCP_PROBE_INIT) kcp->probe_wait = IKCP_PROBE_INIT;
                kcp->probe_wait += kcp->probe_wait / 2;
                if (kcp->probe_wait > IKCP_PROBE_LIMIT) kcp->probe_wait = IKCP_PROBE_LIMIT;
                kcp->ts_probe = kcp->current + kcp->probe_wait;
                kcp->probe |= IKCP_ASK_SEND;
            }
        }
    } else {
        kcp->ts_probe = 0;
        kcp->probe_wait = 0;
    }

    if (kcp->probe & IKCP_ASK_SEND) {
        seg.cmd = IKCP_CMD_WASK;
        size = (int)(ptr - buffer);
        if (size + (int)IKCP_OVERHEAD > (int)kcp->mtu) {
            kcp->output(buffer, size, kcp, kcp->user);
            ptr = buffer;
        }
        ptr = ikcp_encode_seg(ptr, &seg);
    }
    if (kcp->probe & IKCP_ASK_TELL) {
        seg.cmd = IKCP_CMD_WINS;
        size = (int)(ptr - buffer);
        if (size + (int)IKCP_OVERHEAD > (int)kcp->mtu) {
            kcp->output(buffer, size, kcp, kcp->user);
            ptr = buffer;
        }
        ptr = ikcp_encode_seg(ptr, &seg);
    }
    kcp->probe = 0;

    cwnd = _imin_(kcp->snd_wnd, kcp->rmt_wnd);
    if (kcp->nocwnd == 0) cwnd = _imin_(kcp->cwnd, cwnd);

    while (_itimediff(kcp->snd_nxt, kcp->snd_una + cwnd) < 0) {
        struct IKCPSEG *newseg;
        if (IQUEUE_EMPTY(&kcp->snd_queue)) break;
        newseg = IQUEUE_ENTRY(kcp->snd_queue.next, struct IKCPSEG, node);
        IQUEUE_DEL(&newseg->node);
        IQUEUE_ADD_TAIL(&newseg->node, &kcp->snd_buf);
        kcp->nsnd_que--;
        kcp->nsnd_buf++;
        newseg->conv = kcp->conv;
        newseg->cmd = IKCP_CMD_PUSH;
        newseg->wnd = seg.wnd;
        newseg->ts = current;
        newseg->sn = kcp->snd_nxt++;
        newseg->una = kcp->rcv_nxt;
        newseg->resendts = current;
        newseg->rto = kcp->rx_rto;
        newseg->fastack = 0;
        newseg->xmit = 0;
    }

    resent = (kcp->fastresend > 0) ? (IUINT32)kcp->fastresend : 0xffffffff;

    for (p = kcp->snd_buf.next; p != &kcp->snd_buf; p = p->next) {
        struct IKCPSEG *segment = IQUEUE_ENTRY(p, struct IKCPSEG, node);
        int needsend = 0;
        if (segment->xmit == 0) {
            needsend = 1;
            segment->xmit++;
            segment->rto = kcp->rx_rto;
            segment->resendts = current + segment->rto;
        } else if (_itimediff(current, segment->resendts) >= 0) {
            needsend = 1;
            segment->xmit++;
            kcp->xmit++;
            if (kcp->nodelay == 0) segment->rto += _imax_(segment->rto, (IUINT32)kcp->rx_rto);
            else {
                IINT32 step = (kcp->nodelay < 2) ? ((IINT32)(segment->rto)) : kcp->rx_rto;
                segment->rto += step / 2;
            }
            segment->resendts = current + segment->rto;
            lost = 1;
        } else if (segment->fastack >= resent) {
            if ((int)segment->xmit <= kcp->fastlimit || kcp->fastlimit <= 0) {
                needsend = 1;
                segment->xmit++;
                segment->fastack = 0;
                segment->resendts = current + segment->rto;
                change++;
            }
        }
        if (needsend) {
            int need;
            segment->ts = current;
            segment->wnd = seg.wnd;
            segment->una = kcp->rcv_nxt;
            size = (int)(ptr - buffer);
            need = IKCP_OVERHEAD + segment->len;
            if (size + need > (int)kcp->mtu) {
                kcp->output(buffer, size, kcp, kcp->user);
                ptr = buffer;
            }
            ptr = ikcp_encode_seg(ptr, segment);
            if (segment->len > 0) {
                memcpy(ptr, segment->data, segment->len);
                ptr += segment->len;
            }
            if (segment->xmit >= kcp->dead_link) {
                kcp->state = (IUINT32)-1;
            }
        }
    }

    size = (int)(ptr - buffer);
    if (size > 0) {
        kcp->output(buffer, size, kcp, kcp->user);
    }

    if (change) {
        IUINT32 inflight = kcp->snd_nxt - kcp->snd_una;
        kcp->ssthresh = inflight / 2;
        if (kcp->ssthresh < IKCP_THRESH_MIN) kcp->ssthresh = IKCP_THRESH_MIN;
        kcp->cwnd = kcp->ssthresh + resent;
        kcp->incr = kcp->cwnd * kcp->mss;
    }
    if (lost) {
        kcp->ssthresh = cwnd / 2;
        if (kcp->ssthresh < IKCP_THRESH_MIN) kcp->ssthresh = IKCP_THRESH_MIN;
        kcp->cwnd = 1;
        kcp->incr = kcp->mss;
    }
    if (kcp->cwnd < 1) {
        kcp->cwnd = 1;
        kcp->incr = kcp->mss;
    }
}

void ikcp_update(ikcpcb *kcp, IUINT32 current) {
    IINT32 slap;
    kcp->current = current;
    if (kcp->updated == 0) {
        kcp->updated = 1;
        kcp->ts_flush = kcp->current;
    }
    slap = _itimediff(kcp->current, kcp->ts_flush);
    if (slap >= 10000 || slap < -10000) {
        kcp->ts_flush = kcp->current;
        slap = 0;
    }
    if (slap >= 0) {
        kcp->ts_flush += kcp->interval;
        if (_itimediff(kcp->current, kcp->ts_flush) >= 0) {
            kcp->ts_flush = kcp->current + kcp->interval;
        }
        ikcp_flush(kcp);
    }
}

IUINT32 ikcp_check(const ikcpcb *kcp, IUINT32 current) {
    IUINT32 ts_flush = kcp->ts_flush;
    IINT32 tm_flush = 0x7fffffff;
    IINT32 tm_packet = 0x7fffffff;
    IUINT32 minimal = 0;
    struct IQUEUEHEAD *p;
    if (kcp->updated == 0) return current;
    if (_itimediff(current, ts_flush) >= 10000 || _itimediff(current, ts_flush) < -10000) {
        ts_flush = current;
    }
    if (_itimediff(current, ts_flush) >= 0) return current;
    tm_flush = _itimediff(ts_flush, current);
    for (p = kcp->snd_buf.next; p != &kcp->snd_buf; p = p->next) {
        const struct IKCPSEG *seg = IQUEUE_ENTRY(p, const struct IKCPSEG, node);
        IINT32 diff = _itimediff(seg->resendts, current);
        if (diff <= 0) return current;
        if (diff < tm_packet) tm_packet = diff;
    }
    minimal = (IUINT32)(tm_packet < tm_flush ? tm_packet : tm_flush);
    if (minimal >= kcp->interval) minimal = kcp->interval;
    return current + minimal;
}

int ikcp_setmtu(ikcpcb *kcp, int mtu) {
    char *buffer;
    if (mtu < 50 || mtu < (int)IKCP_OVERHEAD) return -1;
    buffer = (char*)ikcp_malloc((mtu + IKCP_OVERHEAD) * 3);
    if (buffer == NULL) return -2;
    kcp->mtu = mtu;
    kcp->mss = kcp->mtu - IKCP_OVERHEAD;
    ikcp_free(kcp->buffer);
    kcp->buffer = buffer;
    return 0;
}

int ikcp_nodelay(ikcpcb *kcp, int nodelay, int interval, int resend, int nc) {
    if (nodelay >= 0) {
        kcp->nodelay = nodelay;
        if (nodelay) kcp->rx_minrto = IKCP_RTO_NDL;
        else kcp->rx_minrto = IKCP_RTO_MIN;
    }
    if (interval >= 0) {
        if (interval > 5000) interval = 5000;
        else if (interval < 10) interval = 10;
        kcp->interval = interval;
    }
    if (resend >= 0) kcp->fastresend = resend;
    if (nc >= 0) kcp->nocwnd = nc;
    return 0;
}

int ikcp_wndsize(ikcpcb *kcp, int sndwnd, int rcvwnd) {
    if (kcp) {
        if (sndwnd > 0) kcp->snd_wnd = sndwnd;
        if (rcvwnd > 0) kcp->rcv_wnd = _imax_(rcvwnd, IKCP_WND_RCV);
    }
    return 0;
}

int ikcp_waitsnd(const ikcpcb *kcp) {
    return kcp->nsnd_buf + kcp->nsnd_que;
}

int ikcp_input(ikcpcb *kcp, const char *data, long size) {
    IUINT32 prev_una = kcp->snd_una;
    IUINT32 maxack = 0, latest_ts = 0;
    int flag = 0;
    if (data == NULL || (long)size < (long)IKCP_OVERHEAD) return -1;
    while (1) {
        IUINT32 ts, sn, len, una, conv;
        IUINT16 wnd;
        IUINT8 cmd, frg;
        struct IKCPSEG *seg;
        if (size < (long)IKCP_OVERHEAD) break;
        ikcp_decode32u(data, &conv);
        if (conv != kcp->conv) return -1;
        ikcp_decode8u(data + 4, &cmd);
        ikcp_decode8u(data + 5, &frg);
        ikcp_decode16u(data + 6, &wnd);
        ikcp_decode32u(data + 8, &ts);
        ikcp_decode32u(data + 12, &sn);
        ikcp_decode32u(data + 16, &una);
        ikcp_decode32u(data + 20, &len);
        data += IKCP_OVERHEAD;
        size -= IKCP_OVERHEAD;
        if ((long)size < (long)len || (int)len < 0) return -2;
        if (cmd != IKCP_CMD_PUSH && cmd != IKCP_CMD_ACK &&
            cmd != IKCP_CMD_WASK && cmd != IKCP_CMD_WINS) return -3;
        kcp->rmt_wnd = wnd;
        ikcp_parse_una(kcp, una);
        ikcp_shrink_buf(kcp);
        if (cmd == IKCP_CMD_ACK) {
            if (_itimediff(kcp->current, ts) >= 0) {
                ikcp_update_ack(kcp, _itimediff(kcp->current, ts));
            }
            ikcp_parse_ack(kcp, sn);
            ikcp_shrink_buf(kcp);
            if (flag == 0) {
                flag = 1;
                maxack = sn;
                latest_ts = ts;
            } else {
                if (_itimediff(sn, maxack) > 0) {
                    maxack = sn;
                    latest_ts = ts;
                }
            }
        } else if (cmd == IKCP_CMD_PUSH) {
            if (_itimediff(sn, kcp->rcv_nxt + kcp->rcv_wnd) < 0) {
                ikcp_ack_push(kcp, sn, ts);
                if (_itimediff(sn, kcp->rcv_nxt) >= 0) {
                    seg = ikcp_segment_new(kcp, len);
                    seg->conv = conv;
                    seg->cmd = cmd;
                    seg->frg = frg;
                    seg->wnd = wnd;
                    seg->ts = ts;
                    seg->sn = sn;
                    seg->una = una;
                    seg->len = len;
                    if (len > 0) memcpy(seg->data, data, len);
                    // Insert into rcv_buf ordered by sn
                    int repeat = 0;
                    struct IQUEUEHEAD *p;
                    for (p = kcp->rcv_buf.prev; p != &kcp->rcv_buf; p = p->prev) {
                        struct IKCPSEG *s = IQUEUE_ENTRY(p, struct IKCPSEG, node);
                        if (s->sn == sn) { repeat = 1; break; }
                        if (_itimediff(sn, s->sn) > 0) break;
                    }
                    if (repeat == 0) {
                        IQUEUE_INIT(&seg->node);
                        IQUEUE_ADD(&seg->node, p);
                        kcp->nrcv_buf++;
                    } else {
                        ikcp_segment_delete(kcp, seg);
                    }
                    // Move consecutive segments from rcv_buf to rcv_queue
                    while (!IQUEUE_EMPTY(&kcp->rcv_buf)) {
                        seg = IQUEUE_ENTRY(kcp->rcv_buf.next, struct IKCPSEG, node);
                        if (seg->sn == kcp->rcv_nxt && kcp->nrcv_que < kcp->rcv_wnd) {
                            IQUEUE_DEL(&seg->node);
                            kcp->nrcv_buf--;
                            IQUEUE_ADD_TAIL(&seg->node, &kcp->rcv_queue);
                            kcp->nrcv_que++;
                            kcp->rcv_nxt++;
                        } else {
                            break;
                        }
                    }
                }
            }
        } else if (cmd == IKCP_CMD_WASK) {
            kcp->probe |= IKCP_ASK_TELL;
        } else if (cmd == IKCP_CMD_WINS) {
            // Do nothing
        }
        data += len;
        size -= len;
    }
    if (flag != 0) {
        ikcp_parse_fastack(kcp, maxack, latest_ts);
    }
    if (_itimediff(kcp->snd_una, prev_una) > 0) {
        if (kcp->cwnd < kcp->rmt_wnd) {
            IUINT32 mss = kcp->mss;
            if (kcp->cwnd < kcp->ssthresh) {
                kcp->cwnd++;
                kcp->incr += mss;
            } else {
                if (kcp->incr == 0) {
                    kcp->incr = mss;
                    kcp->cwnd = 1;
                }
                kcp->incr += (mss * mss) / kcp->incr + (mss / 16);
                if ((kcp->cwnd + 1) * mss <= kcp->incr) {
                    kcp->cwnd = (kcp->incr + mss - 1) / ((mss > 0)? mss : 1);
                }
            }
            if (kcp->cwnd > kcp->rmt_wnd) {
                kcp->cwnd = kcp->rmt_wnd;
                kcp->incr = kcp->rmt_wnd * mss;
            }
        }
    }
    return 0;
}
