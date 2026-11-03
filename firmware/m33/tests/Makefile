# Host unit tests (no Zephyr needed): make -C firmware/m33/tests
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -g

host_test: host_test.c ../src/fsm.c ../src/drive.c ../src/protocol.c
	$(CC) $(CFLAGS) -o $@ $^

.PHONY: test clean
test: host_test
	./host_test

clean:
	rm -f host_test
