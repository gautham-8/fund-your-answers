<script setup>
import { confirmState, settleConfirm } from '../lib/confirm'
import Modal from './Modal.vue'
</script>

<template>
  <Modal :open="confirmState.open" :title="confirmState.title" size="sm" @close="settleConfirm(false)">
    <p class="text-sm text-slate-600">{{ confirmState.message }}</p>
    <template #footer>
      <button class="btn-secondary" @click="settleConfirm(false)">Cancel</button>
      <button :class="confirmState.danger ? 'btn-danger' : 'btn-primary'" @click="settleConfirm(true)">{{ confirmState.confirmText }}</button>
    </template>
  </Modal>
</template>
